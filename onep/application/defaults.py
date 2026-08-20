"""Concrete OnePTeam capabilities built from existing proven algorithms."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from onep.application.capabilities import Capability, CapabilityRegistry
from onep.application.projects import create_project
from onep.application.project_actions import (
    article_generate,
    analysis_export,
    artifact_list,
    artifact_read,
    candidate_decide,
    candidate_list,
    memory_search,
    memory_status,
    project_detail,
    project_delete,
)
from onep.application.service import ApplicationService, RequestContext
from onep.application.workflows import analysis_handler, optimization_handler
from onep.domain import Problem, RunRecord, RunStatus
from onep.greenfield.models import GreenfieldOptions
from onep.harness.persistence import load_harness_run
from onep.infrastructure import ControlStore
from onep.persistence.database import database_path, init_db, list_projects


def control_store_path() -> Path:
    return database_path()


def build_application(path: str | Path | None = None) -> ApplicationService:
    store = ControlStore(path or control_store_path())
    return ApplicationService(build_registry(store), store)


def build_registry(store: ControlStore) -> CapabilityRegistry:
    registry = CapabilityRegistry([
        Capability(
            "capability.list",
            "List available capabilities",
            lambda *_: {"capabilities": registry.describe()},
        ),
        Capability("project.list", "List projects", _list_projects),
        Capability("project.detail", "Get project workbench", project_detail),
        Capability(
            "project.create",
            "Create project",
            _create_project,
            mutating=True,
            input_schema={
                "type": "object",
                "required": ["requirement"],
                "properties": {
                    "requirement": {"type": "string"},
                    "name": {"type": "string"},
                    "workspace_path": {"type": "string"},
                    "options": {"type": "object"},
                },
            },
        ),
        Capability(
            "run.start",
            "Start autonomous run",
            _run_handler(store),
            mutating=True,
            background=True,
            input_schema={
                "type": "object",
                "required": ["project"],
                "properties": {"project": {"type": "string"}},
            },
        ),
        Capability(
            "run.resume",
            "Resume autonomous run",
            _run_handler(store, resume=True),
            mutating=True,
            background=True,
        ),
        Capability("run.status", "Get run status", _run_status),
        Capability(
            "run.stop",
            "Stop at the next safe boundary",
            _stop_run,
            mutating=True,
        ),
        Capability("artifact.list", "List project artifacts", artifact_list),
        Capability("artifact.read", "Read a project artifact", artifact_read),
        Capability("candidate.list", "List improvement candidates", candidate_list),
        Capability(
            "candidate.decide",
            "Approve, reject, or rescore a candidate",
            _v2_only(store, candidate_decide),
            mutating=True,
        ),
        Capability(
            "article.generate",
            "Generate a project knowledge article",
            _v2_only(store, article_generate),
            mutating=True,
            background=True,
        ),
        Capability("memory.status", "Get memory statistics", memory_status),
        Capability("memory.search", "Search persistent memory", memory_search),
        Capability("analysis.export", "Export analysis results", analysis_export),
        Capability(
            "project.delete",
            "Delete a project record",
            project_delete,
            mutating=True,
        ),
        Capability(
            "analysis.start",
            "Analyze an existing codebase",
            analysis_handler(store),
            mutating=True,
            background=True,
        ),
        Capability(
            "optimization.start",
            "Analyze and improve an existing Git repository",
            optimization_handler(store),
            mutating=True,
            background=True,
        ),
    ])
    return registry


def resolve_project(ref: str):
    init_db()
    matches = [
        project
        for project in list_projects()
        if project.name == ref or project.id == ref or project.id.startswith(ref)
    ]
    if len(matches) != 1:
        code = "project_not_found" if not matches else "project_reference_ambiguous"
        raise Problem(code, "Project not found", f"Unable to resolve project: {ref}")
    return matches[0]


def _project_dict(project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "mode": project.mode.value,
        "status": project.status.value,
        "current_stage": project.current_stage,
        "workspace_path": project.workspace_path,
        "requirement": project.requirement,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _list_projects(_payload, _context) -> dict[str, Any]:
    init_db()
    from onep.web.state import project_summaries

    return {"projects": project_summaries(list_projects())}


def _create_project(payload, _context) -> dict[str, Any]:
    requirement = str(payload.get("requirement") or "").strip()
    if not requirement:
        raise Problem(
            "requirement_required",
            "Requirement is required",
            "Describe what the project should accomplish.",
            actionable=True,
        )
    raw_options = dict(payload.get("options") or {})
    options = GreenfieldOptions.from_dict(raw_options)
    workspace = str(payload.get("workspace_path") or "").strip()
    project = create_project(
        requirement,
        name=str(payload.get("name") or "").strip() or None,
        workspace=Path(workspace).expanduser() if workspace else None,
        options=options,
    )
    return {"project": _project_dict(project)}


def _v2_only(store: ControlStore, handler):
    def guarded(payload, context):
        project = resolve_project(str(payload.get("project") or context.project_id))
        if store.latest_run_for_project(project.id) is None:
            raise Problem(
                "legacy_project_read_only",
                "Historical project is read-only",
                "Create a V2 run before using mutating workbench actions.",
                actionable=True,
                suggested_actions=("create_new_project",),
            )
        return handler(payload, context)

    return guarded


def _run_handler(store: ControlStore, *, resume: bool = False):
    def run(payload, context: RequestContext) -> dict[str, Any]:
        project = resolve_project(str(payload.get("project") or context.project_id))
        existing = store.latest_run_for_project(project.id)
        run_id = context.run_id or (
            existing.id if resume and existing is not None else uuid4().hex
        )
        if store.get_run(run_id) is None:
            store.create_run(RunRecord(
                id=run_id,
                project_id=project.id,
                goal_version=max(1, int(payload.get("goal_version") or 1)),
                workflow=str(payload.get("workflow") or "autonomous"),
                options=dict(payload.get("options") or {}),
            ))
        store.update_run(run_id, status=RunStatus.RUNNING, stage="understand")
        store.append_event(
            "run.started",
            {"project": project.name, "trace_id": context.trace_id},
            project_id=project.id,
            run_id=run_id,
        )
        from onep.orchestrator.runner import run_pipeline

        try:
            run_options = GreenfieldOptions.from_dict(payload.get("options"))
            completed = run_pipeline(project.name, options=run_options)
        except Exception as exc:
            store.update_run(run_id, status=RunStatus.FAILED, stage="failed")
            store.append_event(
                "run.failed",
                {"detail": str(exc), "trace_id": context.trace_id},
                project_id=project.id,
                run_id=run_id,
            )
            raise
        latest = resolve_project(project.id)
        if completed:
            status, stage = RunStatus.COMPLETED, "stop"
        elif latest.status.value == "paused":
            status, stage = RunStatus.PAUSED, latest.current_stage or "paused"
        else:
            status, stage = RunStatus.FAILED, latest.current_stage or "failed"
        store.update_run(run_id, status=status, stage=stage)
        store.append_event(
            f"run.{status.value}",
            {"project": project.name, "trace_id": context.trace_id},
            project_id=project.id,
            run_id=run_id,
        )
        return {"completed": completed, "run_id": run_id}

    return run


def _run_status(payload, context: RequestContext) -> dict[str, Any]:
    project = resolve_project(str(payload.get("project") or context.project_id))
    harness = load_harness_run(Path(project.workspace_path))
    return {
        "project": _project_dict(project),
        "run": harness.to_dict() if harness else None,
    }


def _stop_run(payload, context: RequestContext) -> dict[str, Any]:
    project = resolve_project(str(payload.get("project") or context.project_id))
    from onep.harness.interventions import request_stop

    request_stop(Path(project.workspace_path))
    return {"requested": True, "boundary": "next_iteration"}
