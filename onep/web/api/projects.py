"""REST endpoints for projects, runs, candidates, and article triggering."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from onep.cli.create import create_project, default_project_name
from onep.greenfield.models import GreenfieldOptions
from onep.harness.persistence import load_harness_run
from onep.persistence.database import init_db, list_projects
from onep.web import runtime, state as harness_state

router = APIRouter(prefix="/api", tags=["projects"])


def _project_by_name(name: str):
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == name), None)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {name}")
    return project


@router.get("/projects")
def projects_list():
    init_db()
    return {"projects": harness_state.project_summaries()}


@router.post("/projects", status_code=201)
def projects_create(payload: dict):
    requirement = str((payload or {}).get("requirement") or "").strip()
    if not requirement:
        raise HTTPException(status_code=400, detail="requirement is required")
    name = str((payload or {}).get("name") or "").strip() or default_project_name(requirement)
    init_db()
    if any(project.name == name for project in list_projects()):
        raise HTTPException(status_code=409, detail=f"project already exists: {name}")
    workspace = runtime.workspace_for(name)
    project = create_project(requirement, name=name, workspace=workspace,
                             options=GreenfieldOptions())
    return {
        "id": project.id, "name": project.name, "mode": project.mode.value,
        "status": project.status.value, "workspace_path": project.workspace_path,
        "requirement": project.requirement,
        "spawn": runtime.spawn_run(name, workspace),
    }


@router.get("/projects/{name}")
def projects_detail(name: str):
    project = _project_by_name(name)
    detail = harness_state.run_detail(Path(project.workspace_path))
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no harness run yet for {name}")
    return detail


@router.get("/projects/{name}/log")
def projects_log(name: str, offset: int = 0, limit: int = 200):
    project = _project_by_name(name)
    entries = harness_state.log_entries(
        Path(project.workspace_path), offset=offset, limit=min(limit, 500))
    next_offset = entries[-1]["offset"] + 1 if entries else offset
    return {"entries": entries, "next_offset": next_offset}


@router.post("/projects/{name}/stop")
def projects_stop(name: str):
    project = _project_by_name(name)
    from onep.harness.interventions import request_stop
    request_stop(Path(project.workspace_path))
    return {"ok": True, "note": "stop requested at the next iteration boundary"}
