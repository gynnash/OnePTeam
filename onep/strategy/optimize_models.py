"""Serializable data models for optimize run orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar


EnumT = TypeVar("EnumT", bound=Enum)


class PlanStatus(str, Enum):
    PENDING = "pending"
    PLANNED = "planned"
    PLAN_READY = "plan_ready"
    BRANCH_CREATED = "branch_created"
    DEVELOPING = "developing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    REPAIRING = "repairing"
    FIXING = "fixing"
    PASSED = "passed"
    COMMITTED = "committed"
    INTEGRATING = "integrating"
    INTEGRATED = "integrated"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureReason(str, Enum):
    PLAN_GENERATION_FAILED = "plan_generation_failed"
    DEPENDENCY_FAILED = "dependency_failed"
    BRANCH_CREATE_FAILED = "branch_create_failed"
    DEVELOPER_FAILED = "developer_failed"
    NO_CHANGES = "no_changes"
    TEST_FAILED = "test_failed"
    REVIEW_FAILED = "review_failed"
    FIX_ATTEMPTS_EXHAUSTED = "fix_attempts_exhausted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CHERRY_PICK_CONFLICT = "cherry_pick_conflict"
    INTEGRATION_TEST_FAILED = "integration_test_failed"
    INTERNAL_ERROR = "internal_error"
    COMMIT_FAILED = "commit_failed"
    CANCELLED = "cancelled"
    ROLLBACK_FAILED = "rollback_failed"
    REGRESSION_DETECTED = "regression_detected"
    INVALID_PLAN_METADATA = "invalid_plan_metadata"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_serialize(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _required(data: dict[str, Any], field_name: str) -> Any:
    value = data.get(field_name)
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value


def _required_string(data: dict[str, Any], field_name: str) -> str:
    value = _required(data, field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _string_or_default(
    data: dict[str, Any],
    field_name: str,
    default: str = "",
) -> str:
    value = data.get(field_name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _container_or_empty(data: dict[str, Any], field_name: str) -> Any:
    value = data.get(field_name)
    return () if value is None else value


def _enum_value(
    enum_type: type[EnumT],
    value: Any,
    field_name: str,
    default: EnumT | None = None,
) -> EnumT:
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"{field_name} is required")
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unknown {field_name}: {value!r}") from exc


def _strict_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{field_name} must be true or false")


@dataclass
class ReviewResult:
    passed: bool
    summary: str = ""
    findings: list[Any] = field(default_factory=list)
    blocking_issues: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized = []
        supplied_blockers = bool(self.blocking_issues)
        source = self.blocking_issues or self.findings or []
        for issue in source:
            if isinstance(issue, str):
                normalized.append({"file": "?", "line": None, "message": issue})
            elif isinstance(issue, dict):
                normalized.append({
                    "file": str(issue.get("file") or "?"),
                    "line": issue.get("line"),
                    "message": str(issue.get("message") or ""),
                })
            else:
                continue
        self.blocking_issues = normalized
        if supplied_blockers and self.blocking_issues and not self.findings:
            self.findings = []
            for issue in self.blocking_issues:
                location = issue["file"]
                if issue["line"] is not None:
                    location += f":{issue['line']}"
                self.findings.append(f"{location}: {issue['message']}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "findings": list(self.findings),
            "blocking_issues": _serialize(self.blocking_issues),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewResult:
        return cls(
            passed=_strict_bool(data.get("passed"), "passed"),
            summary=_string_or_default(data, "summary"),
            findings=list(data.get("findings") or []),
            blocking_issues=list(
                data.get("blocking_issues")
                or []
            ),
        )


@dataclass
class TestCommandResult:
    __test__ = False

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    started_at: str = ""
    ended_at: str = ""
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "timed_out": self.timed_out,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCommandResult:
        exit_code = _required(data, "exit_code")
        return cls(
            command=_required_string(data, "command"),
            exit_code=int(exit_code),
            stdout=_string_or_default(data, "stdout"),
            stderr=_string_or_default(data, "stderr"),
            duration_seconds=float(data.get("duration_seconds") or 0.0),
            started_at=_string_or_default(data, "started_at"),
            ended_at=_string_or_default(data, "ended_at"),
            timed_out=bool(data.get("timed_out", False)),
        )


@dataclass
class AttemptRecord:
    number: int
    branch: str
    base_commit: str
    changed_files: set[Path] = field(default_factory=set)
    test_results: list[TestCommandResult] = field(default_factory=list)
    review: ReviewResult | None = None
    cost: float = 0.0
    feedback: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    token_usage: list[dict[str, Any]] = field(default_factory=list)
    stage_costs: dict[str, float | None] = field(default_factory=dict)
    status: str = "running"

    def __post_init__(self) -> None:
        self.artifacts = _serialize(self.artifacts or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "branch": self.branch,
            "base_commit": self.base_commit,
            "changed_files": _serialize(self.changed_files),
            "test_results": [result.to_dict() for result in self.test_results],
            "review": self.review.to_dict() if self.review else None,
            "cost": self.cost,
            "feedback": list(self.feedback),
            "artifacts": _serialize(self.artifacts),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "token_usage": _serialize(self.token_usage),
            "stage_costs": _serialize(self.stage_costs),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttemptRecord:
        review = data.get("review")
        return cls(
            number=int(_required(data, "number")),
            branch=_required_string(data, "branch"),
            base_commit=_required_string(data, "base_commit"),
            changed_files={
                Path(path)
                for path in _container_or_empty(data, "changed_files")
            },
            test_results=[
                TestCommandResult.from_dict(result)
                for result in _container_or_empty(data, "test_results")
            ],
            review=ReviewResult.from_dict(review) if review is not None else None,
            cost=float(data.get("cost") or 0.0),
            feedback=list(_container_or_empty(data, "feedback")),
            artifacts=dict(_container_or_empty(data, "artifacts")),
            started_at=_string_or_default(data, "started_at"),
            ended_at=_string_or_default(data, "ended_at"),
            token_usage=list(_container_or_empty(data, "token_usage")),
            stage_costs=dict(_container_or_empty(data, "stage_costs")),
            status=_string_or_default(data, "status", "running"),
        )


@dataclass
class PlanCandidate:
    id: str
    title: str
    summary: str = ""
    tags: set[str] = field(default_factory=set)
    impact: str = "medium"
    files: set[Path] = field(default_factory=set)
    dependencies: set[str] = field(default_factory=set)
    test_commands: tuple[str, ...] = ()
    fingerprint: str = ""
    risk_flags: set[str] = field(default_factory=set)
    discovery_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "tags": _serialize(self.tags),
            "impact": self.impact,
            "files": _serialize(self.files),
            "dependencies": _serialize(self.dependencies),
            "test_commands": list(self.test_commands),
            "fingerprint": self.fingerprint,
            "risk_flags": _serialize(self.risk_flags),
            "discovery_index": self.discovery_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanCandidate:
        return cls(
            id=_required_string(data, "id"),
            title=_required_string(data, "title"),
            summary=_string_or_default(data, "summary"),
            tags=set(_container_or_empty(data, "tags")),
            impact=_string_or_default(data, "impact", "medium"),
            files={
                Path(path) for path in _container_or_empty(data, "files")
            },
            dependencies=set(_container_or_empty(data, "dependencies")),
            test_commands=tuple(_container_or_empty(data, "test_commands")),
            fingerprint=_string_or_default(data, "fingerprint"),
            risk_flags=set(_container_or_empty(data, "risk_flags")),
            discovery_index=int(data.get("discovery_index") or 0),
        )


_ALLOWED_PLAN_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    PlanStatus.PENDING: {
        PlanStatus.PLANNED,
        PlanStatus.PLAN_READY,
        PlanStatus.FAILED,
        PlanStatus.SKIPPED,
    },
    PlanStatus.PLANNED: {
        PlanStatus.PLAN_READY,
        PlanStatus.BRANCH_CREATED,
        PlanStatus.DEVELOPING,
        PlanStatus.FAILED,
        PlanStatus.SKIPPED,
    },
    PlanStatus.PLAN_READY: {
        PlanStatus.BRANCH_CREATED, PlanStatus.FAILED, PlanStatus.SKIPPED,
    },
    PlanStatus.BRANCH_CREATED: {
        PlanStatus.DEVELOPING, PlanStatus.FAILED,
    },
    PlanStatus.DEVELOPING: {
        PlanStatus.TESTING,
        PlanStatus.FAILED,
    },
    PlanStatus.TESTING: {
        PlanStatus.REVIEWING,
        PlanStatus.REPAIRING,
        PlanStatus.FIXING,
        PlanStatus.FAILED,
    },
    PlanStatus.REVIEWING: {
        PlanStatus.REPAIRING,
        PlanStatus.FIXING,
        PlanStatus.COMMITTED,
        PlanStatus.PASSED,
        PlanStatus.FAILED,
    },
    PlanStatus.REPAIRING: {
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.FAILED,
    },
    PlanStatus.FIXING: {
        PlanStatus.DEVELOPING, PlanStatus.TESTING, PlanStatus.FAILED,
    },
    PlanStatus.PASSED: {
        PlanStatus.COMMITTED, PlanStatus.FAILED,
    },
    PlanStatus.COMMITTED: {
        PlanStatus.INTEGRATING,
        PlanStatus.INTEGRATED,
        PlanStatus.FAILED,
    },
    PlanStatus.INTEGRATING: {
        PlanStatus.INTEGRATED, PlanStatus.FAILED,
    },
    PlanStatus.FAILED: {PlanStatus.ROLLED_BACK},
    PlanStatus.INTEGRATED: set(),
    PlanStatus.ROLLED_BACK: set(),
    PlanStatus.SKIPPED: set(),
}


@dataclass
class PlanRecord:
    candidate: PlanCandidate
    status: PlanStatus = PlanStatus.PENDING
    branch: str = ""
    base_commit: str = ""
    commit_sha: str = ""
    attempts: list[AttemptRecord] = field(default_factory=list)
    failure_reason: FailureReason | None = None
    failure_detail: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = _enum_value(
            PlanStatus,
            self.status,
            "status",
        )
        if self.failure_reason is not None:
            self.failure_reason = _enum_value(
                FailureReason,
                self.failure_reason,
                "failure_reason",
            )
        self.artifacts = _serialize(self.artifacts or {})

    def transition_to(self, status: PlanStatus | str) -> None:
        status = _enum_value(
            PlanStatus,
            status,
            "status",
        )
        if status == self.status:
            return
        if status not in _ALLOWED_PLAN_TRANSITIONS[self.status]:
            raise ValueError(
                f"Illegal plan status transition: {self.status.value} -> "
                f"{status.value}"
            )
        self.status = status

    def fail(self, reason: FailureReason | str, detail: str = "") -> None:
        reason = _enum_value(FailureReason, reason, "failure_reason")
        self.transition_to(PlanStatus.FAILED)
        self.failure_reason = reason
        self.failure_detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "status": self.status.value,
            "branch": self.branch,
            "base_commit": self.base_commit,
            "commit_sha": self.commit_sha,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "failure_reason": (
                self.failure_reason.value if self.failure_reason else None
            ),
            "failure_detail": self.failure_detail,
            "artifacts": _serialize(self.artifacts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanRecord:
        reason = data.get("failure_reason")
        candidate = _required(data, "candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a mapping")
        return cls(
            candidate=PlanCandidate.from_dict(candidate),
            status=_enum_value(
                PlanStatus,
                data.get("status"),
                "status",
                PlanStatus.PENDING,
            ),
            branch=_string_or_default(data, "branch"),
            base_commit=_string_or_default(data, "base_commit"),
            commit_sha=_string_or_default(data, "commit_sha"),
            attempts=[
                AttemptRecord.from_dict(attempt)
                for attempt in _container_or_empty(data, "attempts")
            ],
            failure_reason=(
                _enum_value(FailureReason, reason, "failure_reason")
                if reason is not None
                else None
            ),
            failure_detail=_string_or_default(data, "failure_detail"),
            artifacts=dict(_container_or_empty(data, "artifacts")),
        )


@dataclass
class RunRecord:
    id: str
    project_name: str
    source_path: Path
    status: RunStatus = RunStatus.PENDING
    plans: list[PlanRecord] = field(default_factory=list)
    total_cost: float = 0.0
    base_commit: str = ""
    integration_branch: str = ""
    failure_reason: FailureReason | None = None
    failure_detail: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    base_branch: str = ""
    integration_commit: str = ""
    budget: float = 0.0
    spent: float = 0.0
    remaining: float | None = None
    started_at: str = field(default_factory=_now)
    ended_at: str = ""
    status_counts: dict[str, int] = field(default_factory=dict)
    cost_entries: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = _enum_value(
            RunStatus,
            self.status,
            "status",
        )
        if self.failure_reason is not None:
            self.failure_reason = _enum_value(
                FailureReason,
                self.failure_reason,
                "failure_reason",
            )
        self.artifacts = _serialize(self.artifacts or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "source_path": str(self.source_path),
            "status": self.status.value,
            "plans": [plan.to_dict() for plan in self.plans],
            "total_cost": self.total_cost,
            "base_commit": self.base_commit,
            "integration_branch": self.integration_branch,
            "failure_reason": (
                self.failure_reason.value if self.failure_reason else None
            ),
            "failure_detail": self.failure_detail,
            "artifacts": _serialize(self.artifacts),
            "base_branch": self.base_branch,
            "integration_commit": self.integration_commit,
            "budget": self.budget,
            "spent": self.spent,
            "remaining": self.remaining,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status_counts": _serialize(self.status_counts),
            "cost_entries": _serialize(self.cost_entries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        reason = data.get("failure_reason")
        return cls(
            id=_required_string(data, "id"),
            project_name=_required_string(data, "project_name"),
            source_path=Path(_required_string(data, "source_path")),
            status=_enum_value(
                RunStatus,
                data.get("status"),
                "status",
                RunStatus.PENDING,
            ),
            plans=[
                PlanRecord.from_dict(plan)
                for plan in _container_or_empty(data, "plans")
            ],
            total_cost=float(data.get("total_cost") or 0.0),
            base_commit=_string_or_default(data, "base_commit"),
            integration_branch=_string_or_default(data, "integration_branch"),
            failure_reason=(
                _enum_value(FailureReason, reason, "failure_reason")
                if reason is not None
                else None
            ),
            failure_detail=_string_or_default(data, "failure_detail"),
            artifacts=dict(_container_or_empty(data, "artifacts")),
            base_branch=_string_or_default(data, "base_branch"),
            integration_commit=_string_or_default(data, "integration_commit"),
            budget=float(data.get("budget") or 0.0),
            spent=float(data.get("spent") or 0.0),
            remaining=(
                float(data["remaining"]) if data.get("remaining") is not None
                else None
            ),
            started_at=_string_or_default(data, "started_at"),
            ended_at=_string_or_default(data, "ended_at"),
            status_counts=dict(_container_or_empty(data, "status_counts")),
            cost_entries=list(_container_or_empty(data, "cost_entries")),
        )
