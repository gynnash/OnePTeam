"""Read-side views over harness state files.

The web console is a pure consumer: every function here reads harness state
(run.yaml, flow-events.jsonl, recorder JSONL files) and returns plain dicts
for the API layer. Nothing here mutates state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from onep.harness.models import HarnessRun
from onep.harness.persistence import load_harness_run
from onep.harness.states import HarnessStage


def harness_root(workspace: Path) -> Path:
    return Path(workspace) / ".onep" / "harness"


def flow_events_path(workspace: Path) -> Path:
    return harness_root(workspace) / "flow-events.jsonl"


def resolve_run_dir(workspace: Path) -> Path | None:
    run = load_harness_run(workspace)
    if run is None:
        return None
    if run.mode == "greenfield" and run.greenfield_run is not None:
        return Path(workspace) / ".onep" / "greenfield" / "runs" / run.greenfield_run.id
    return Path(workspace) / ".onep" / "optimize" / "runs" / run.id


def last_flow_stage(workspace: Path) -> str:
    """Current harness stage from the tail of flow-events.jsonl."""
    stage = ""
    path = flow_events_path(workspace)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = (json.loads(line) or {}).get("payload") or {}
            except json.JSONDecodeError:
                continue
            stage = str(payload.get("stage") or stage)
    return stage


def stage_history(workspace: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    path = flow_events_path(workspace)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            payload = raw.get("payload") or {}
            entries.append({
                "type": str(raw.get("type") or "flow_transition"),
                "stage": str(payload.get("stage") or ""),
                "iteration": int(payload.get("iteration") or 0),
                "payload": payload,
            })
    return entries


def run_summary(workspace: Path) -> dict[str, Any] | None:
    run = load_harness_run(workspace)
    if run is None:
        return None
    return {
        "id": run.id,
        "project_name": run.project_name,
        "mode": run.mode,
        "status": run.status,
        "stage": last_flow_stage(workspace) or run.stage,
        "iteration": run.iteration,
        "spent": run.spent,
        "stop_reason": (run.stop_state or {}).get("reason", ""),
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "goal": run.original_goal,
    }


def project_summaries(projects=None) -> list[dict[str, Any]]:
    if projects is None:
        from onep.persistence.database import list_projects
        projects = list_projects()
    rows = []
    for project in projects:
        workspace = Path(project.workspace_path).resolve()
        rows.append({
            "id": project.id,
            "name": project.name,
            "mode": project.mode.value,
            "status": project.status.value,
            "current_stage": project.current_stage,
            "workspace_path": str(workspace),
            "requirement": project.requirement,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "harness": run_summary(workspace),
        })
    return rows


def run_detail(workspace: Path) -> dict[str, Any] | None:
    run = load_harness_run(workspace)
    if run is None:
        return None
    return {
        "id": run.id,
        "project_name": run.project_name,
        "mode": run.mode,
        "original_goal": run.original_goal,
        "status": run.status,
        "stage": last_flow_stage(workspace) or run.stage,
        "iteration": run.iteration,
        "spent": run.spent,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "options": run.options.to_dict(),
        "stop_state": run.stop_state,
        "quality_history": [snap.to_dict() for snap in run.quality_history],
        "improvement_candidates": [
            candidate.to_dict() for candidate in run.improvement_candidates
        ],
        "work_items": [item.to_dict() for item in run.work_items],
        "knowledge_events": list(run.knowledge_events),
        "research_reports": list(run.research_reports),
        "stages": [stage.value for stage in HarnessStage],
        "stage_history": stage_history(workspace),
    }


def log_entries(workspace: Path, offset: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    """Recorder events from the run's events.jsonl, sliced by line offset."""
    run_dir = resolve_run_dir(workspace)
    if run_dir is None:
        return []
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(0, offset)
    entries = []
    for index in range(start, min(len(lines), start + max(1, limit))):
        line = lines[index].strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            entry = {"offset": index, **raw}
            entries.append(entry)
    return entries
