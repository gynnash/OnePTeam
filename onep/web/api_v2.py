"""Public Product Studio API v2."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Header, Query, Request, Response

from onep.application import RequestContext
from onep.domain import Job

if TYPE_CHECKING:
    from onep.studio import StudioService


router = APIRouter(prefix="/api/v2", tags=["product-studio"])


def _studio(request: Request) -> "StudioService":
    service = getattr(request.app.state, "studio_service", None)
    if service is None:
        from onep.studio import StudioService

        service = StudioService()
        request.app.state.studio_service = service
    return service


def _application(request: Request):
    application = request.app.state.application
    if application is None:
        from onep.application.studio_defaults import build_application

        application = build_application()
        request.app.state.application = application
    return application


def _job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "capability_id": job.capability_id,
        "project_id": job.project_id,
        "run_id": job.run_id,
        "status": job.status.value,
        "attempts": job.attempts,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _article_profile(value: dict[str, Any]) -> dict[str, Any]:
    """Never expose an OS credential reference through the public API."""
    return {
        key: item
        for key, item in value.items()
        if key not in {"credential_ref", "credential"}
    } | {
        "credential_source": "os_keyring"
        if value.get("credential_configured")
        else "missing"
    }


def _write(
    request: Request, action_id: str, operation: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """Apply the v2 idempotency contract to a state-changing operation."""
    service = _studio(request)
    resolved = action_id or uuid4().hex
    replay = service.store.action_result(resolved)
    if replay is not None:
        return replay
    result = operation()
    service.store.remember_action(resolved, result)
    return result


@router.get("/health")
def health(request: Request):
    worker = _application(request).store.worker_health()
    return {
        "status": "ready" if worker["ready"] else "degraded",
        "database": "ready",
        "worker": worker,
        "runtime": "codex_app_server",
    }


@router.get("/projects")
def projects(request: Request):
    return {"projects": _studio(request).store.list_projects()}


@router.post("/projects", status_code=201)
def create_project(
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).create_project(
        payload, action_id=x_action_id or uuid4().hex
    )


@router.get("/projects/{project_id}/studio")
def project_studio(project_id: str, request: Request):
    return _studio(request).studio(project_id)


@router.get("/projects/{project_id}/discovery")
def project_discovery(project_id: str, request: Request):
    service = _studio(request)
    service.store.get_project(project_id)
    return service.store.discovery_snapshot(project_id)


@router.post("/projects/{project_id}/discovery/answers")
def answer_discovery(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).answer_discovery(
        project_id, payload, action_id=x_action_id or uuid4().hex
    )


@router.post("/projects/{project_id}/discovery/decision")
def decide_discovery(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).decide_discovery(
        project_id, payload, action_id=x_action_id or uuid4().hex
    )


@router.post("/projects/{project_id}/discovery/reassess")
def reassess_discovery(
    project_id: str,
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).reassess_discovery(
        project_id, action_id=x_action_id or uuid4().hex
    )


@router.post("/projects/{project_id}/prd/{version}/approve", status_code=202)
def approve_prd(
    project_id: str,
    version: int,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    action_id = x_action_id or uuid4().hex
    result = _studio(request).approve_prd(
        project_id, version, payload, action_id=action_id
    )
    job = _application(request).execute(
        "studio.execute",
        {"project_id": project_id},
        context=RequestContext(project_id=project_id, run_id=result["release"]["id"]),
        action_id=f"{action_id}:execute",
    )
    return {**result, "execution": {"status": job.status, "job_id": job.job_id}}


@router.post("/projects/{project_id}/prd/{version}/feedback")
def feedback_prd(
    project_id: str,
    version: int,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).feedback_prd(
        project_id, version, payload, action_id=x_action_id or uuid4().hex
    )


@router.post("/projects/{project_id}/prd/{version}/revalidate")
def revalidate_prd(
    project_id: str,
    version: int,
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).revalidate_prd(project_id, version),
    )


@router.post("/projects/{project_id}/prd/{version}/assumptions/{assumption_id}/resolve")
def resolve_prd_assumption(
    project_id: str,
    version: int,
    assumption_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).resolve_prd_assumption(
            project_id, version, assumption_id, payload
        ),
    )


@router.post("/projects/{project_id}/changes")
def propose_change(
    project_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _studio(request).propose_change(
        project_id, payload, action_id=x_action_id or uuid4().hex
    )


@router.put("/projects/{project_id}/features/{feature_id}/strategy")
def update_strategy(
    project_id: str,
    feature_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).set_feature_strategy(project_id, feature_id, payload),
    )


@router.post("/interactions/{interaction_id}/resolve")
def resolve_interaction(
    interaction_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).resolve_interaction(interaction_id, payload),
    )


@router.post("/projects/{project_id}/{action}")
def project_action(
    project_id: str,
    action: str,
    request: Request,
    x_action_id: str = Header(default=""),
):
    if action not in {"pause", "resume", "stop"}:
        from onep.domain import Problem

        raise Problem("invalid_project_action", "Invalid project action", action)
    action_id = x_action_id or uuid4().hex
    result = _write(
        request,
        action_id,
        lambda: {"project": _studio(request).set_project_state(project_id, action)},
    )
    if action == "resume" and result["project"]["state"] == "ready":
        release = _studio(request).store.current_release(project_id)
        job = _application(request).execute(
            "studio.execute",
            {"project_id": project_id},
            context=RequestContext(
                project_id=project_id,
                run_id=str((release or {}).get("id") or ""),
            ),
            action_id=f"{action_id}:resume",
        )
        result = {
            **result,
            "execution": {"status": job.status, "job_id": job.job_id},
        }
    return result


@router.get("/projects/{project_id}/events")
def project_events(project_id: str, request: Request, after: int = Query(0, ge=0)):
    return {"events": _studio(request).store.events(project_id, after)}


@router.get("/runtime/jobs")
def jobs(request: Request):
    return {"jobs": [_job(job) for job in _application(request).store.jobs(100)]}


@router.post("/runtime/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    return _job(_application(request).store.request_cancel(job_id))


@router.get("/knowledge/search")
def search_knowledge(
    request: Request,
    q: str = "",
    project_id: list[str] = Query(default=[]),
    stack: list[str] = Query(default=[]),
    component: list[str] = Query(default=[]),
    error_signature: str = "",
    include_invalid: bool = False,
    limit: int = Query(20, ge=1, le=50),
):
    return {
        "records": _studio(request).knowledge.search(
            q,
            project_ids=project_id,
            technology_stack=stack,
            components=component,
            error_signature=error_signature,
            include_invalid=include_invalid,
            limit=limit,
        )
    }


@router.get("/knowledge/records/{knowledge_id}")
def knowledge_record(knowledge_id: str, request: Request):
    return _studio(request).store.get_knowledge(knowledge_id)


@router.patch("/knowledge/records/{knowledge_id}")
def update_knowledge(
    knowledge_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).store.update_knowledge(
            knowledge_id,
            dict(payload.get("patch") or {}),
            int(payload.get("revision") or 0),
        ),
    )


@router.get("/projects/{project_id}/knowledge")
def project_knowledge(project_id: str, request: Request):
    service = _studio(request)
    return {
        "records": service.store.knowledge_rows(project_id),
        "applications": service.store.knowledge_applications(project_id),
    }


@router.get("/knowledge/relations")
def knowledge_relations(request: Request, project_id: str = ""):
    return {"applications": _studio(request).store.knowledge_applications(project_id)}


@router.post("/knowledge/records/{knowledge_id}/feedback")
def knowledge_feedback(
    knowledge_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).knowledge.feedback(
            knowledge_id,
            str(payload.get("target_project_id") or ""),
            str(payload.get("feature_id") or ""),
            str(payload.get("phase") or "manual"),
            str(payload.get("result") or ""),
            str(payload.get("feedback") or ""),
        ),
    )


@router.post("/articles/source-suggestions")
def article_source_suggestions(payload: dict[str, Any], request: Request):
    return _studio(request).articles.source_suggestions(
        [str(v) for v in payload.get("project_ids") or ()],
        str(payload.get("query") or ""),
        int(payload.get("limit") or 20),
    )


@router.post("/articles/source-packs", status_code=201)
def create_source_pack(
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).articles.create_source_pack(
            [str(v) for v in payload.get("project_ids") or ()],
            [str(v) for v in payload.get("knowledge_ids") or ()],
            replacements={
                str(key): str(value)
                for key, value in dict(payload.get("replacements") or {}).items()
            },
        ),
    )


@router.post("/articles/source-packs/{pack_id}/confirm")
def confirm_source_pack(
    pack_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).store.confirm_source_pack(
            pack_id, int(payload.get("revision") or 0)
        ),
    )


@router.get("/articles")
def articles(request: Request):
    return {"articles": _studio(request).store.articles()}


@router.post("/articles", status_code=201)
def generate_article(
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).articles.generate(
            dict(payload.get("brief") or {}),
            str(payload.get("source_pack_id") or ""),
            model_profile_id=str(payload.get("model_profile_id") or ""),
        ),
    )


@router.get("/articles/{article_id}")
def article(article_id: str, request: Request, version: int | None = None):
    return _studio(request).store.get_article(article_id, version)


@router.put("/articles/{article_id}/drafts/{version}")
def update_article(
    article_id: str,
    version: int,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).articles.update_draft(article_id, version, payload),
    )


@router.post("/articles/{article_id}/regenerate")
def regenerate_article(
    article_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).articles.regenerate(
            article_id,
            int(payload.get("version") or 0),
            platform=str(payload.get("platform") or "both"),
            instructions=str(payload.get("instructions") or ""),
        ),
    )


@router.post("/articles/{article_id}/export")
def export_article(article_id: str, payload: dict[str, Any], request: Request):
    result = _studio(request).articles.export(
        article_id,
        str(payload.get("platform") or "long"),
        str(payload.get("format") or "markdown"),
    )
    return Response(
        content=result["content"],
        media_type=result["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'},
    )


@router.get("/settings/article-models")
def article_models(request: Request):
    return {
        "profiles": [
            _article_profile(value)
            for value in _studio(request).store.article_model_profiles()
        ]
    }


@router.post("/settings/article-models", status_code=201)
def create_article_model(
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _article_profile(_studio(request).articles.save_model_profile(payload)),
    )


@router.put("/settings/article-models/{profile_id}")
def update_article_model(
    profile_id: str,
    payload: dict[str, Any],
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _article_profile(
            _studio(request).articles.save_model_profile({**payload, "id": profile_id})
        ),
    )


@router.delete("/settings/article-models/{profile_id}")
def delete_article_model(
    profile_id: str,
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _article_profile(
            _studio(request).articles.delete_model_profile(profile_id)
        ),
    )


@router.post("/settings/article-models/{profile_id}/test")
def test_article_model(
    profile_id: str,
    request: Request,
    x_action_id: str = Header(default=""),
):
    return _write(
        request,
        x_action_id,
        lambda: _studio(request).articles.test_model_profile(profile_id),
    )


@router.post("/settings/runtime/test")
def test_runtime(request: Request, x_action_id: str = Header(default="")):
    return _write(
        request,
        x_action_id,
        lambda: _application(request).execute("settings.runtime.test").data,
    )
