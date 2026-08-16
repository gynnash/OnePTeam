"""REST endpoints for projects, runs, candidates, and article triggering."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from onep.cli.create import create_project, default_project_name
from onep.greenfield.models import GreenfieldOptions
from onep.harness.article import ArticleSynthesizer
from onep.harness.interventions import merged_candidates, record_candidate_decision
from onep.harness.persistence import load_harness_run
from onep.harness.vault import VaultWriter, global_vault_root
from onep.llm.adapters import LLMAdapter
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


@router.get("/projects/{name}/candidates")
def projects_candidates(name: str):
    project = _project_by_name(name)
    run = load_harness_run(Path(project.workspace_path))
    if run is None:
        return {"candidates": []}
    return {"candidates": merged_candidates(run, Path(project.workspace_path))}


@router.post("/projects/{name}/candidates/{candidate_id}/approve")
def candidate_approve(name: str, candidate_id: str, payload: dict | None = None):
    return _candidate_decision(name, candidate_id, "approve", payload)


@router.post("/projects/{name}/candidates/{candidate_id}/reject")
def candidate_reject(name: str, candidate_id: str, payload: dict | None = None):
    return _candidate_decision(name, candidate_id, "reject", payload)


@router.post("/projects/{name}/candidates/{candidate_id}/rescore")
def candidate_rescore(name: str, candidate_id: str, payload: dict | None = None):
    if (payload or {}).get("score") is None:
        raise HTTPException(status_code=400, detail="score is required")
    return _candidate_decision(name, candidate_id, "rescore", payload)


def _candidate_decision(name, candidate_id, decision, payload):
    project = _project_by_name(name)
    workspace = Path(project.workspace_path)
    run = load_harness_run(workspace)
    if run is None or not any(c.id == candidate_id for c in run.improvement_candidates):
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}")
    entry = record_candidate_decision(
        workspace, candidate_id, decision,
        score=(payload or {}).get("score") if decision == "rescore" else None,
        note=str((payload or {}).get("note") or ""),
    )
    return {"ok": True, "decision": entry}


@router.post("/projects/{name}/article")
def project_article(name: str):
    project = _project_by_name(name)
    workspace = Path(project.workspace_path).resolve()
    run = load_harness_run(workspace)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no harness run yet for {name}")
    run_dir = harness_state.resolve_run_dir(workspace)
    writer = VaultWriter(global_vault_root())
    synthesizer = ArticleSynthesizer(LLMAdapter(), writer)
    result = synthesizer.synthesize(workspace, run_dir, run)
    return {"title": result["title"],
            "article_path": str(result["article_path"]),
            "graph_path": str(result["graph_path"])}
