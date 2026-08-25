"""V2 domain records.

These types intentionally contain no database, Click, FastAPI, or model code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Problem(Exception):
    """Stable, user-facing failure returned by every application entry point."""

    code: str
    title: str
    detail: str = ""
    actionable: bool = False
    suggested_actions: tuple[str, ...] = ()
    trace_id: str = ""

    def __str__(self) -> str:
        return self.detail or self.title

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "actionable": self.actionable,
            "suggested_actions": list(self.suggested_actions),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class ActionResult:
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    job_id: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "job_id": self.job_id,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class Job:
    id: str
    capability_id: str
    payload: dict[str, Any]
    project_id: str = ""
    run_id: str = ""
    actor: str = "local-user"
    action_id: str = ""
    mutating: bool = True
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    lease_owner: str = ""
    lease_until: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
