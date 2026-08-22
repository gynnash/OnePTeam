"""One application boundary used by CLI, REST actions, and workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from onep.application.capabilities import CapabilityRegistry
from onep.domain import ActionResult, Problem


@dataclass(frozen=True)
class RequestContext:
    actor: str = "local-user"
    project_id: str = ""
    run_id: str = ""
    job_id: str = ""
    trace_id: str = ""

    def with_trace(self) -> "RequestContext":
        if self.trace_id:
            return self
        return RequestContext(
            actor=self.actor,
            project_id=self.project_id,
            run_id=self.run_id,
            job_id=self.job_id,
            trace_id=uuid4().hex,
        )


class ApplicationService:
    def __init__(self, registry: CapabilityRegistry, store) -> None:
        self.registry = registry
        self.store = store

    def execute(
        self,
        capability_id: str,
        payload: dict[str, Any] | None = None,
        *,
        context: RequestContext | None = None,
        action_id: str | None = None,
        wait: bool = False,
    ) -> ActionResult:
        capability = self.registry.get(capability_id)
        request = (context or RequestContext()).with_trace()
        body = dict(payload or {})
        self.store.append_event(
            "action.requested",
            {
                "capability_id": capability.id,
                "actor": request.actor,
                "trace_id": request.trace_id,
            },
            project_id=request.project_id,
            run_id=request.run_id,
        )
        if capability.background and not wait:
            job = self.store.enqueue_job(
                capability.id,
                body,
                project_id=request.project_id,
                run_id=request.run_id,
                actor=request.actor,
                action_id=action_id or uuid4().hex,
                mutating=capability.mutating,
                trace_id=request.trace_id,
            )
            return ActionResult(
                status=job.status.value,
                job_id=job.id,
                trace_id=request.trace_id,
            )
        try:
            data = capability.handler(body, request) or {}
        except Problem:
            raise
        except Exception as exc:
            raise Problem(
                code="action_failed",
                title="Action failed",
                detail=str(exc),
                actionable=True,
                suggested_actions=("retry",),
                trace_id=request.trace_id,
            ) from exc
        self.store.append_event(
            "action.completed",
            {
                "capability_id": capability.id,
                "actor": request.actor,
                "trace_id": request.trace_id,
            },
            project_id=request.project_id,
            run_id=request.run_id,
        )
        return ActionResult(
            status="succeeded",
            data=data,
            trace_id=request.trace_id,
        )
