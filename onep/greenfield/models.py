"""Serializable models for the Greenfield engineering loop."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string_list(value: Any, *, collapse_legacy_chars: bool = False) -> list[str]:
    """Normalize model/YAML scalar-or-list fields without splitting strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    raw_items = [str(item) for item in value]
    if (
        collapse_legacy_chars and len(raw_items) > 1
        and all(len(item) == 1 for item in raw_items)
    ):
        joined = "".join(raw_items)
        return [joined] if joined.strip() else []
    return [item for item in raw_items if item.strip()]


class GreenfieldStage(str, Enum):
    INIT = "init"
    DISCOVER = "discover"
    ACCEPTANCE = "acceptance"
    ARCHITECT = "architect"
    PLAN_SLICES = "plan_slices"
    IMPLEMENT = "implement"
    VERIFY_SLICE = "verify_slice"
    REPAIR = "repair"
    REVIEW = "review"
    ARCHITECTURE_REVIEW = "architecture_review"
    FULL_VERIFY = "full_verify"
    DEPLOY_VERIFY = "deploy_verify"
    FINISHED = "finished"


class GreenfieldStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class GreenfieldOptions:
    max_rounds: int = 100
    max_repairs_per_slice: int = 8
    max_cost: float = 0.0
    test_commands: list[str] = field(default_factory=list)
    deploy_mode: str = "verify"
    non_interactive: bool = False
    verbose: bool = False
    default_model: str = ""
    default_provider: str = ""
    complex_model: str = ""
    complex_provider: str = ""

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        migrate_legacy: bool = True,
    ) -> "GreenfieldOptions":
        raw = data or {}
        max_rounds = max(1, int(raw.get("max_rounds", 100)))
        if migrate_legacy and max_rounds == 12:
            max_rounds = 100
        max_repairs = max(1, int(raw.get("max_repairs_per_slice", 8)))
        if migrate_legacy and max_repairs == 3:
            max_repairs = 8
        return cls(
            max_rounds=max_rounds,
            max_repairs_per_slice=max_repairs,
            max_cost=max(0.0, float(raw.get("max_cost", 0.0))),
            test_commands=_string_list(raw.get("test_commands")),
            deploy_mode=str(raw.get("deploy_mode") or "verify"),
            non_interactive=bool(raw.get("non_interactive", False)),
            verbose=bool(raw.get("verbose", False)),
            default_model=str(raw.get("default_model") or ""),
            default_provider=str(raw.get("default_provider") or ""),
            complex_model=str(raw.get("complex_model") or ""),
            complex_provider=str(raw.get("complex_provider") or ""),
        )

    @classmethod
    def configured(cls, data: dict[str, Any] | None = None) -> "GreenfieldOptions":
        """Merge explicit values over non-secret global run defaults."""
        from dataclasses import asdict as _asdict
        from onep.config import load_config

        raw = _asdict(load_config().run_defaults)
        raw.update({key: value for key, value in (data or {}).items() if value is not None})
        return cls.from_dict(raw, migrate_legacy=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptanceItem:
    id: str
    priority: str
    behavior: str
    commands: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    status: str = "pending"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AcceptanceItem":
        verification = data.get("verification") or {}
        return cls(
            id=str(data.get("id") or "REQ-001"),
            priority=str(data.get("priority") or "P1").upper(),
            behavior=str(data.get("behavior") or "Requirement is satisfied"),
            commands=_string_list(
                verification.get("commands") or data.get("commands") or []
                , collapse_legacy_chars=True
            ),
            evidence=_string_list(
                verification.get("evidence") or data.get("evidence") or []
                , collapse_legacy_chars=True
            ),
            status=str(data.get("status") or "pending"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority,
            "behavior": self.behavior,
            "verification": {
                "commands": list(self.commands),
                "evidence": list(self.evidence),
            },
            "status": self.status,
        }


@dataclass
class AcceptanceContract:
    items: list[AcceptanceItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AcceptanceContract":
        values = data.get("requirements") or data.get("items") or []
        return cls([AcceptanceItem.from_dict(item) for item in values])

    def to_dict(self) -> dict[str, Any]:
        return {"requirements": [item.to_dict() for item in self.items]}

    @property
    def required_complete(self) -> bool:
        # Compatibility convenience for persisted runs. Runtime completion is
        # decided by harness.acceptance.evaluate_acceptance, which also checks
        # gates, review blockers, and the current tree fingerprint.
        from onep.harness.acceptance import evaluate_acceptance

        return evaluate_acceptance(self, hard_gates_passed=True).satisfied


@dataclass
class SlicePlan:
    id: str
    title: str
    objective: str
    acceptance_ids: list[str]
    expected_files: list[str]
    focused_commands: list[str] = field(default_factory=list)
    status: str = "pending"
    attempts: int = 0
    commit_sha: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = 0) -> "SlicePlan":
        return cls(
            id=str(data.get("id") or f"slice-{index + 1}"),
            title=str(data.get("title") or f"Slice {index + 1}"),
            objective=str(data.get("objective") or data.get("summary") or ""),
            acceptance_ids=_string_list(data.get("acceptance_ids")),
            expected_files=_string_list(data.get("expected_files")),
            focused_commands=_string_list(
                data.get("focused_commands"), collapse_legacy_chars=True
            ),
            status=str(data.get("status") or "pending"),
            attempts=int(data.get("attempts") or 0),
            commit_sha=str(data.get("commit_sha") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GreenfieldRun:
    """Kernel-owned engineering checkpoint kept compatible with historical runs."""
    id: str
    project_name: str
    requirement: str
    workspace: str
    stage: GreenfieldStage = GreenfieldStage.INIT
    status: GreenfieldStatus = GreenfieldStatus.PENDING
    options: GreenfieldOptions = field(default_factory=GreenfieldOptions)
    base_branch: str = ""
    base_commit: str = ""
    run_branch: str = ""
    round_number: int = 0
    current_slice: int = 0
    slices: list[SlicePlan] = field(default_factory=list)
    failure_reason: str = ""
    failure_detail: str = ""
    blocked_question: str = ""
    last_assessment_fingerprint: str = ""
    last_assessment_missing: list[str] = field(default_factory=list)
    last_assessment_satisfied: bool = False
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    spent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "stage": self.stage.value,
            "status": self.status.value,
            "options": self.options.to_dict(),
            "options_schema_version": 2,
            "slices": [item.to_dict() for item in self.slices],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GreenfieldRun":
        return cls(
            id=str(data["id"]),
            project_name=str(data["project_name"]),
            requirement=str(data.get("requirement") or ""),
            workspace=str(data["workspace"]),
            stage=GreenfieldStage(data.get("stage", "init")),
            status=GreenfieldStatus(data.get("status", "pending")),
            options=GreenfieldOptions.from_dict(
                data.get("options"),
                migrate_legacy=int(data.get("options_schema_version") or 1) < 2,
            ),
            base_branch=str(data.get("base_branch") or ""),
            base_commit=str(data.get("base_commit") or ""),
            run_branch=str(data.get("run_branch") or ""),
            round_number=int(data.get("round_number") or 0),
            current_slice=int(data.get("current_slice") or 0),
            slices=[
                SlicePlan.from_dict(item, index)
                for index, item in enumerate(data.get("slices") or [])
            ],
            failure_reason=str(data.get("failure_reason") or ""),
            failure_detail=str(data.get("failure_detail") or ""),
            blocked_question=str(data.get("blocked_question") or ""),
            last_assessment_fingerprint=str(
                data.get("last_assessment_fingerprint") or ""
            ),
            last_assessment_missing=list(
                data.get("last_assessment_missing") or []
            ),
            last_assessment_satisfied=bool(
                data.get("last_assessment_satisfied", False)
            ),
            started_at=str(data.get("started_at") or _now()),
            ended_at=str(data.get("ended_at") or ""),
            spent=float(data.get("spent") or 0.0),
        )
