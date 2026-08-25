"""Small capability-driven interface for engineering execution backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


RuntimeEventSink = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class RuntimeCapabilities:
    persistent_sessions: bool = False
    structured_output: bool = False
    streaming: bool = False
    interrupt: bool = False
    steer: bool = False
    compact: bool = False
    fork: bool = False
    review: bool = False
    archive: bool = False
    goal: bool = False
    approvals: bool = False
    skills: bool = False
    plan: bool = False
    user_input: bool = False
    detached_review: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeProbe:
    backend_id: str
    available: bool
    detail: str
    capabilities: RuntimeCapabilities
    authentication: str = "unknown"
    models: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = self.capabilities.to_dict()
        return data


@dataclass(frozen=True)
class ExecutionRequest:
    project_id: str
    run_id: str
    work_item_id: str
    attempt: int
    workspace: Path
    objective: str
    contract_id: str
    contract_version: int
    baseline_fingerprint: str
    instructions: str = ""
    acceptance_rule_ids: tuple[str, ...] = ()
    expected_paths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    failure_evidence_ids: tuple[str, ...] = ()
    feedback: str = ""
    mode: str = "implement"
    model: str = ""
    model_provider: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 0
    deadline_seconds: int = 3600
    strategy: str = "direct"
    sanitized_knowledge_context: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    backend_id: str
    status: str
    final_response: str
    session_id: str = ""
    turn_id: str = ""
    changed_files: tuple[str, ...] = ()
    commands_attempted: tuple[str, ...] = ()
    unresolved_blockers: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    events: tuple[dict[str, Any], ...] = ()
    termination_reason: str = "completed"
    plan: tuple[dict[str, Any], ...] = ()
    review_findings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RuntimeGoal:
    thread_id: str
    objective: str
    status: str
    token_budget: int = 0
    tokens_used: int = 0
    time_used_seconds: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeGoal":
        return cls(
            thread_id=str(data.get("threadId") or data.get("thread_id") or ""),
            objective=str(data.get("objective") or ""),
            status=str(data.get("status") or ""),
            token_budget=int(data.get("tokenBudget") or data.get("token_budget") or 0),
            tokens_used=int(data.get("tokensUsed") or data.get("tokens_used") or 0),
            time_used_seconds=int(
                data.get("timeUsedSeconds") or data.get("time_used_seconds") or 0
            ),
        )


class EngineeringRuntime(Protocol):
    backend_id: str

    def probe(self) -> RuntimeProbe: ...

    def start_session(self, request: ExecutionRequest) -> str: ...

    def resume_session(self, session_id: str, request: ExecutionRequest) -> str: ...

    def execute(
        self,
        request: ExecutionRequest,
        *,
        event_sink: RuntimeEventSink | None = None,
    ) -> ExecutionResult: ...

    def interrupt(self, session_id: str) -> bool: ...

    def close(self) -> None: ...


class SteerableRuntime(Protocol):
    def steer(self, session_id: str, instruction: str) -> bool: ...


class CompactableRuntime(Protocol):
    def compact(self, session_id: str) -> bool: ...


class ForkableRuntime(Protocol):
    def fork(self, session_id: str, request: ExecutionRequest) -> str: ...


class ArchivableRuntime(Protocol):
    def archive(self, session_id: str) -> bool: ...


class GoalRuntime(Protocol):
    def set_goal(
        self, session_id: str, objective: str, token_budget: int = 0
    ) -> RuntimeGoal: ...

    def get_goal(self, session_id: str) -> RuntimeGoal | None: ...

    def complete_goal(self, session_id: str) -> bool: ...

    def clear_goal(self, session_id: str) -> bool: ...
