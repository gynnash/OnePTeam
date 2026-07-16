"""Typed deterministic shell around autonomous Optimize work."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from onep.strategy.optimize_models import PlanCandidate, PlanStatus


class OptimizeFlowStage(str, Enum):
    INIT = "init"
    DISCOVER = "discover"
    PLAN = "plan"
    SCHEDULE = "schedule"
    DEVELOP = "develop"
    INTEGRATE = "integrate"
    VERIFY = "verify"
    CONVERGED = "converged"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED = {
    OptimizeFlowStage.INIT: {OptimizeFlowStage.DISCOVER},
    OptimizeFlowStage.DISCOVER: {
        OptimizeFlowStage.PLAN,
        OptimizeFlowStage.CONVERGED,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.PLAN: {
        OptimizeFlowStage.SCHEDULE,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.SCHEDULE: {
        OptimizeFlowStage.DEVELOP,
        OptimizeFlowStage.VERIFY,
        OptimizeFlowStage.CONVERGED,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.DEVELOP: {
        OptimizeFlowStage.INTEGRATE,
        OptimizeFlowStage.VERIFY,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.INTEGRATE: {
        OptimizeFlowStage.DEVELOP,
        OptimizeFlowStage.VERIFY,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.VERIFY: {
        OptimizeFlowStage.DISCOVER,
        OptimizeFlowStage.FINISHED,
        OptimizeFlowStage.FAILED,
        OptimizeFlowStage.CANCELLED,
    },
    OptimizeFlowStage.CONVERGED: {OptimizeFlowStage.FINISHED},
    OptimizeFlowStage.FINISHED: set(),
    OptimizeFlowStage.FAILED: set(),
    OptimizeFlowStage.CANCELLED: set(),
}


@dataclass(frozen=True)
class OptimizeFlowEvent:
    stage: OptimizeFlowStage
    round_number: int
    payload: dict[str, Any]


class OptimizeFlow:
    def __init__(
        self,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.stage = OptimizeFlowStage.INIT
        self.round_number = 0
        self.events: list[OptimizeFlowEvent] = []
        self.event_sink = event_sink

    def start_round(self, round_number: int) -> None:
        if round_number < 1:
            raise ValueError("round_number must be positive")
        self.round_number = round_number
        self.transition(OptimizeFlowStage.DISCOVER)

    def transition(
        self,
        stage: OptimizeFlowStage,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if stage not in _ALLOWED[self.stage]:
            raise ValueError(
                f"Illegal optimize flow transition: {self.stage.value} -> "
                f"{stage.value}"
            )
        self.stage = stage
        event = OptimizeFlowEvent(stage, self.round_number, payload or {})
        self.events.append(event)
        if self.event_sink:
            self.event_sink("flow_transition", {
                "stage": stage.value,
                "round": self.round_number,
                **event.payload,
            })

    def converge(self, reason: str) -> None:
        self.transition(OptimizeFlowStage.CONVERGED, {"reason": reason})

    def classify_discoveries(
        self,
        candidates: list[PlanCandidate],
        fingerprint_registry: dict[str, PlanStatus],
        scheduler,
    ) -> tuple[list[PlanCandidate], list[PlanCandidate]]:
        """Split new work from rediscovered, previously integrated issues."""
        regressions = []
        eligible = []
        for candidate in candidates:
            candidate.fingerprint = (
                candidate.fingerprint or scheduler.fingerprint(candidate)
            )
            if (
                fingerprint_registry.get(candidate.fingerprint)
                == PlanStatus.INTEGRATED
            ):
                regressions.append(candidate)
            else:
                eligible.append(candidate)
        fresh = scheduler.new_candidates(
            eligible,
            set(fingerprint_registry),
        )
        return fresh, regressions

    def finish(self) -> None:
        if self.stage == OptimizeFlowStage.CONVERGED:
            self.transition(OptimizeFlowStage.FINISHED)
        elif self.stage == OptimizeFlowStage.VERIFY:
            self.transition(OptimizeFlowStage.FINISHED)
        elif self.stage != OptimizeFlowStage.FINISHED:
            raise ValueError(f"Cannot finish flow from {self.stage.value}")

    def fail(self, message: str) -> None:
        if OptimizeFlowStage.FAILED in _ALLOWED[self.stage]:
            self.transition(OptimizeFlowStage.FAILED, {"message": message})

    def cancel(self) -> None:
        if OptimizeFlowStage.CANCELLED in _ALLOWED[self.stage]:
            self.transition(OptimizeFlowStage.CANCELLED)
