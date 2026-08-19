"""Unified harness stage machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class HarnessStage(str, Enum):
    INIT = "init"
    UNDERSTAND = "understand"
    RESEARCH = "research"
    DESIGN = "design"
    PLAN = "plan"
    BUILD = "build"
    VERIFY = "verify"
    REVIEW = "review"
    REFLECT = "reflect"
    DISCOVER = "discover"
    PRIORITIZE = "prioritize"
    STOP = "stop"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED: dict[HarnessStage, set[HarnessStage]] = {
    HarnessStage.INIT: {HarnessStage.UNDERSTAND},
    HarnessStage.UNDERSTAND: {
        HarnessStage.RESEARCH,
        HarnessStage.PLAN,
        HarnessStage.STOP,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.RESEARCH: {
        HarnessStage.DESIGN,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.DESIGN: {
        HarnessStage.PLAN,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.PLAN: {
        HarnessStage.BUILD,
        HarnessStage.STOP,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.BUILD: {
        HarnessStage.VERIFY,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.VERIFY: {
        HarnessStage.REVIEW,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.REVIEW: {
        HarnessStage.REFLECT,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.REFLECT: {
        HarnessStage.DISCOVER,
        HarnessStage.STOP,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.DISCOVER: {
        HarnessStage.PRIORITIZE,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.PRIORITIZE: {
        HarnessStage.RESEARCH,
        HarnessStage.STOP,
        HarnessStage.FAILED,
        HarnessStage.CANCELLED,
    },
    HarnessStage.STOP: set(),
    HarnessStage.FAILED: set(),
    HarnessStage.CANCELLED: set(),
}


@dataclass(frozen=True)
class HarnessFlowEvent:
    stage: HarnessStage
    iteration: int
    payload: dict[str, Any]


class HarnessFlow:
    def __init__(
        self,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.stage = HarnessStage.INIT
        self.iteration = 0
        self.events: list[HarnessFlowEvent] = []
        self.event_sink = event_sink

    def start_iteration(self, iteration: int) -> None:
        if iteration < 1:
            raise ValueError("iteration must be positive")
        self.iteration = iteration

    def transition(
        self,
        stage: HarnessStage,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if stage not in _ALLOWED[self.stage]:
            raise ValueError(
                f"Illegal harness transition: {self.stage.value} -> {stage.value}"
            )
        self.stage = stage
        event = HarnessFlowEvent(stage, self.iteration, payload or {})
        self.events.append(event)
        if self.event_sink:
            self.event_sink(
                "flow_transition",
                {
                    "stage": stage.value,
                    "iteration": self.iteration,
                    **event.payload,
                },
            )

    def fail(self, message: str) -> None:
        if HarnessStage.FAILED in _ALLOWED[self.stage]:
            self.transition(HarnessStage.FAILED, {"message": message})

    def cancel(self) -> None:
        if HarnessStage.CANCELLED in _ALLOWED[self.stage]:
            self.transition(HarnessStage.CANCELLED)
