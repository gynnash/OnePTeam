"""Small lease-based worker for background capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
from uuid import uuid4

from onep.application import CapabilityRegistry, RequestContext
from onep.domain import Job, Problem


@dataclass
class Worker:
    registry: CapabilityRegistry
    store: object
    worker_id: str = ""
    lease_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.worker_id:
            self.worker_id = f"worker-{uuid4().hex[:10]}"

    def run_once(self) -> Job | None:
        job = self.store.claim_job(self.worker_id)
        if job is None:
            return None
        capability = self.registry.get(job.capability_id)
        context = RequestContext(
            actor=job.actor,
            project_id=job.project_id,
            run_id=job.run_id,
            job_id=job.id,
            trace_id=self._trace_id(job),
        )
        heartbeat_stop = Event()
        heartbeat = Thread(
            target=self._heartbeat,
            args=(job.id, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()
        try:
            result = capability.handler(job.payload, context) or {}
            self.store.append_event(
                "action.completed",
                {
                    "capability_id": capability.id,
                    "job_id": job.id,
                    "result": result,
                    "trace_id": context.trace_id,
                },
                project_id=job.project_id,
                run_id=job.run_id,
            )
            return self.store.finish_job(job.id, succeeded=True, result=result)
        except Problem as exc:
            problem = exc.to_dict()
        except Exception as exc:
            problem = Problem(
                code="worker_action_failed",
                title="Background action failed",
                detail=str(exc),
                actionable=True,
                suggested_actions=("retry",),
                trace_id=context.trace_id,
            ).to_dict()
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
        self.store.append_event(
            "action.failed",
            {
                "capability_id": capability.id,
                "job_id": job.id,
                "problem": problem,
                "trace_id": context.trace_id,
            },
            project_id=job.project_id,
            run_id=job.run_id,
        )
        return self.store.finish_job(job.id, succeeded=False, error=problem)

    def _heartbeat(self, job_id: str, stopped: Event) -> None:
        interval = max(0.1, self.lease_seconds / 3)
        while not stopped.wait(interval):
            self.store.worker_heartbeat(self.worker_id)
            if not self.store.heartbeat(
                job_id, self.worker_id, self.lease_seconds
            ):
                return

    def touch(self) -> None:
        """Publish worker readiness even while the queue is idle."""
        self.store.worker_heartbeat(self.worker_id)

    def _trace_id(self, job: Job) -> str:
        events = self.store.events(
            project_id=job.project_id,
            run_id=job.run_id,
            limit=1000,
        )
        for event in reversed(events):
            payload = event.get("payload") or {}
            if payload.get("job_id") == job.id and payload.get("trace_id"):
                return str(payload["trace_id"])
        return uuid4().hex
