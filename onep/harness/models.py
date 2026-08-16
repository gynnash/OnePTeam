"""Serializable models for the unified harness."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from onep.greenfield.models import GreenfieldOptions, GreenfieldRun, SlicePlan
from onep.strategy.optimize_models import PlanCandidate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StopReason(str, Enum):
    GOALS_SATISFIED = "goals_satisfied"
    NO_HIGH_VALUE_WORK = "no_high_value_work"
    DIMINISHING_RETURNS = "diminishing_returns"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_ITERATION = "max_iteration"
    USER_STOP = "user_stop"


@dataclass
class ImprovementCandidate:
    id: str
    title: str
    description: str = ""
    source: str = "brainstorm"
    fingerprint: str = ""
    status: str = "pending"  # pending | backlog | parked | duplicate | integrated

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImprovementCandidate":
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            source=str(data.get("source") or "brainstorm"),
            fingerprint=str(data.get("fingerprint") or ""),
            status=str(data.get("status") or "pending"),
        )


@dataclass
class WorkItem:
    id: str
    title: str
    objective: str = ""
    acceptance_ids: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    focused_commands: list[str] = field(default_factory=list)
    source: str = "slice"  # slice | candidate
    fingerprint: str = ""
    status: str = "pending"
    attempts: int = 0
    commit_sha: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkItem":
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            objective=str(data.get("objective") or ""),
            acceptance_ids=list(data.get("acceptance_ids") or []),
            expected_files=list(data.get("expected_files") or []),
            focused_commands=list(data.get("focused_commands") or []),
            source=str(data.get("source") or "slice"),
            fingerprint=str(data.get("fingerprint") or ""),
            status=str(data.get("status") or "pending"),
            attempts=int(data.get("attempts") or 0),
            commit_sha=str(data.get("commit_sha") or ""),
        )


class SliceAdapter:
    @staticmethod
    def to_work_item(plan: SlicePlan) -> WorkItem:
        return WorkItem(
            id=plan.id,
            title=plan.title,
            objective=plan.objective,
            acceptance_ids=list(plan.acceptance_ids),
            expected_files=list(plan.expected_files),
            focused_commands=list(plan.focused_commands),
            source="slice",
            status=plan.status,
            attempts=plan.attempts,
            commit_sha=plan.commit_sha,
        )

    @staticmethod
    def to_slice_plan(item: WorkItem, index: int = 0) -> SlicePlan:
        return SlicePlan(
            id=item.id,
            title=item.title,
            objective=item.objective,
            acceptance_ids=list(item.acceptance_ids),
            expected_files=list(item.expected_files),
            focused_commands=list(item.focused_commands),
            status=item.status,
            attempts=item.attempts,
            commit_sha=item.commit_sha,
        )


class CandidateAdapter:
    @staticmethod
    def to_work_item(candidate: PlanCandidate) -> WorkItem:
        return WorkItem(
            id=candidate.id,
            title=candidate.title,
            objective=candidate.summary,
            expected_files=sorted(str(path) for path in candidate.files),
            focused_commands=list(candidate.focused_test_commands),
            source="candidate",
            fingerprint=candidate.fingerprint,
        )

    @staticmethod
    def to_plan_candidate(item: WorkItem) -> PlanCandidate:
        return PlanCandidate(
            id=item.id,
            title=item.title,
            summary=item.objective,
            files={Path(path) for path in item.expected_files},
            focused_test_commands=tuple(item.focused_commands),
            fingerprint=item.fingerprint,
        )


def candidate_to_slice(
    candidate: ImprovementCandidate, iteration: int, index: int
) -> SlicePlan:
    return SlicePlan(
        id=f"iter{iteration}-{index + 1}",
        title=candidate.title,
        objective=candidate.description,
        acceptance_ids=[],
        expected_files=[],
        focused_commands=[],
    )


@dataclass
class QualitySnapshot:
    iteration: int
    acceptance_pass_rate: float
    test_pass_rate: float
    goal_coverage: float
    quality_score: float
    hard_gates_passed: bool
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualitySnapshot":
        return cls(
            iteration=int(data.get("iteration") or 0),
            acceptance_pass_rate=float(data.get("acceptance_pass_rate") or 0.0),
            test_pass_rate=float(data.get("test_pass_rate") or 0.0),
            goal_coverage=float(data.get("goal_coverage") or 0.0),
            quality_score=float(data.get("quality_score") or 0.0),
            hard_gates_passed=bool(data.get("hard_gates_passed", False)),
            created_at=str(data.get("created_at") or _now()),
        )


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: StopReason | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessOptions:
    max_rounds: int = 100
    max_cost: float = 0.0
    test_commands: list[str] = field(default_factory=list)
    non_interactive: bool = False
    verbose: bool = False

    @classmethod
    def from_greenfield(cls, options: GreenfieldOptions) -> "HarnessOptions":
        return cls(
            max_rounds=options.max_rounds,
            max_cost=options.max_cost,
            test_commands=list(options.test_commands),
            non_interactive=options.non_interactive,
            verbose=options.verbose,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HarnessOptions":
        raw = data or {}
        return cls(
            max_rounds=max(1, int(raw.get("max_rounds", 100))),
            max_cost=max(0.0, float(raw.get("max_cost", 0.0))),
            test_commands=list(raw.get("test_commands") or []),
            non_interactive=bool(raw.get("non_interactive", False)),
            verbose=bool(raw.get("verbose", False)),
        )


@dataclass
class HarnessRun:
    id: str
    project_name: str
    workspace: str
    mode: str  # greenfield | brownfield
    original_goal: str
    stage: str = "init"
    status: str = "pending"
    options: HarnessOptions = field(default_factory=HarnessOptions)
    greenfield_run: GreenfieldRun | None = None
    work_items: list[WorkItem] = field(default_factory=list)
    improvement_candidates: list[ImprovementCandidate] = field(
        default_factory=list
    )
    quality_history: list[QualitySnapshot] = field(default_factory=list)
    stop_state: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    spent: float = 0.0
    started_at: str = field(default_factory=_now)
    ended_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "greenfield_run": self.greenfield_run.to_dict()
            if self.greenfield_run else None,
            "work_items": [item.to_dict() for item in self.work_items],
            "improvement_candidates": [
                item.to_dict() for item in self.improvement_candidates
            ],
            "quality_history": [
                item.to_dict() for item in self.quality_history
            ],
            "options": self.options.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessRun":
        greenfield_raw = data.get("greenfield_run")
        return cls(
            id=str(data["id"]),
            project_name=str(data["project_name"]),
            workspace=str(data["workspace"]),
            mode=str(data.get("mode") or "greenfield"),
            original_goal=str(data.get("original_goal") or ""),
            stage=str(data.get("stage") or "init"),
            status=str(data.get("status") or "pending"),
            options=HarnessOptions.from_dict(data.get("options")),
            greenfield_run=GreenfieldRun.from_dict(greenfield_raw)
            if greenfield_raw else None,
            work_items=[
                WorkItem.from_dict(item) for item in data.get("work_items") or []
            ],
            improvement_candidates=[
                ImprovementCandidate.from_dict(item)
                for item in data.get("improvement_candidates") or []
            ],
            quality_history=[
                QualitySnapshot.from_dict(item)
                for item in data.get("quality_history") or []
            ],
            stop_state=dict(data.get("stop_state") or {}),
            iteration=int(data.get("iteration") or 0),
            spent=float(data.get("spent") or 0.0),
            started_at=str(data.get("started_at") or _now()),
            ended_at=str(data.get("ended_at") or ""),
        )
