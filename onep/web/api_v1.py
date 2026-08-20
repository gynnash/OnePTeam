"""Versioned V2 API backed by the shared Application Service."""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from onep.application import RequestContext
from onep.application.defaults import resolve_project
from onep.application.projects import default_project_name
from onep.domain import Job
from onep.web.runtime import format_sse, workspace_for


router = APIRouter(prefix="/api/v1", tags=["v2"])


def _application(request: Request):
    application = request.app.state.application
    if application is None:
        from onep.application.defaults import build_application

        application = build_application()
        request.app.state.application = application
    return application


def _job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "capability_id": job.capability_id,
        "project_id": job.project_id,
        "run_id": job.run_id,
        "actor": job.actor,
        "action_id": job.action_id,
        "mutating": job.mutating,
        "status": job.status.value,
        "attempts": job.attempts,
        "lease_owner": job.lease_owner,
        "lease_until": job.lease_until,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/capabilities")
def capabilities(request: Request):
    return {"capabilities": _application(request).registry.describe()}


@router.get("/projects")
def projects(request: Request):
    return _application(request).execute("project.list").data


@router.get("/projects/{project_ref}")
def project_detail(project_ref: str, request: Request):
    return _application(request).execute(
        "project.detail", context=RequestContext(project_id=project_ref)
    ).data


@router.get("/projects/{project_ref}/log")
def project_log(
    project_ref: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    from onep.web.state import log_entries

    project = resolve_project(project_ref)
    entries = log_entries(Path(project.workspace_path), offset=offset, limit=limit)
    next_offset = entries[-1]["offset"] + 1 if entries else offset
    return {"entries": entries, "next_offset": next_offset}


@router.get("/projects/{project_ref}/candidates")
def project_candidates(project_ref: str, request: Request):
    return _application(request).execute(
        "candidate.list", context=RequestContext(project_id=project_ref)
    ).data


@router.post("/projects/{project_ref}/candidates/{candidate_id}/{decision}")
def project_candidate_decision(
    project_ref: str,
    candidate_id: str,
    decision: str,
    request: Request,
    payload: dict[str, Any] | None = None,
):
    return _application(request).execute(
        "candidate.decide",
        {"candidate_id": candidate_id, "decision": decision, **(payload or {})},
        context=RequestContext(project_id=project_ref),
    ).to_dict()


@router.post("/projects/{project_ref}/article", status_code=202)
def project_article(
    project_ref: str,
    request: Request,
    x_action_id: str | None = Header(default=None),
):
    return _application(request).execute(
        "article.generate",
        context=RequestContext(project_id=project_ref),
        action_id=x_action_id,
    ).to_dict()


@router.get("/projects/{project_ref}/knowledge")
def project_knowledge(project_ref: str):
    from onep.web.knowledge import list_notes

    project = resolve_project(project_ref)
    return {"notes": list_notes(Path(project.workspace_path), "project")}


@router.post("/projects", status_code=202)
def create_and_run(
    payload: dict[str, Any],
    request: Request,
    x_action_id: str | None = Header(default=None),
):
    requirement = str(payload.get("requirement") or "").strip()
    name = str(payload.get("name") or "").strip() or default_project_name(requirement)
    source = str(payload.get("workspace_path") or "").strip()
    body = dict(payload)
    body["name"] = name
    body["workspace_path"] = source or str(workspace_for(name))
    application = _application(request)
    created = application.execute(
        "project.create",
        body,
        context=RequestContext(actor="local-user"),
    )
    project = created.data["project"]
    run_id = uuid4().hex
    queued = application.execute(
        "run.start",
        {
            "project": project["id"],
            "workflow": "autonomous",
            "options": dict(payload.get("options") or {}),
        },
        context=RequestContext(
            actor="local-user", project_id=project["id"], run_id=run_id
        ),
        action_id=x_action_id or uuid4().hex,
    )
    return {"project": project, "run_id": run_id, "job_id": queued.job_id}


@router.post("/actions/{capability_id:path}", status_code=202)
def execute_action(
    capability_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str | None = Header(default=None),
    x_actor: str = Header(default="local-user"),
):
    body = dict(payload or {})
    project_id = str(body.pop("project_id", ""))
    run_id = str(body.pop("run_id", ""))
    result = _application(request).execute(
        capability_id,
        body,
        context=RequestContext(
            actor=x_actor or "local-user",
            project_id=project_id,
            run_id=run_id,
        ),
        action_id=x_action_id,
    )
    return result.to_dict()


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, request: Request):
    job = _application(request).store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job(job)


@router.get("/jobs")
def jobs(request: Request, limit: int = Query(50, ge=1, le=200)):
    return {"jobs": [_job(job) for job in _application(request).store.jobs(limit)]}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    application = _application(request)
    job = application.store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.capability_id in {"run.start", "run.resume"} and job.project_id:
        application.execute(
            "run.stop",
            context=RequestContext(
                actor="local-user",
                project_id=job.project_id,
                run_id=job.run_id,
            ),
        )
    return _job(application.store.request_cancel(job_id))


@router.get("/events")
def events(
    request: Request,
    after: int = Query(0, ge=0),
    project_id: str = "",
    run_id: str = "",
    limit: int = Query(500, ge=1, le=1000),
):
    return {
        "events": _application(request).store.events(
            after=after,
            project_id=project_id,
            run_id=run_id,
            limit=limit,
        )
    }


@router.get("/events/stream")
def event_stream(
    request: Request,
    after: int = Query(0, ge=0),
    project_id: str = "",
    run_id: str = "",
):
    store = _application(request).store

    async def stream():
        cursor = after
        last_heartbeat = time.monotonic()
        while not await request.is_disconnected():
            rows = store.events(
                after=cursor,
                project_id=project_id,
                run_id=run_id,
                limit=500,
            )
            for row in rows:
                cursor = row["sequence"]
                yield format_sse(row)
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield format_sse({"type": "heartbeat", "sequence": cursor})
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
