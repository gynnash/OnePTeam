"""Shared seeding helpers for web tests: project rows, harness runs, vaults."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from onep.greenfield.models import GreenfieldOptions, GreenfieldRun
from onep.harness.models import HarnessOptions, HarnessRun
from onep.harness.persistence import save_harness_run
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode


def seed_project(tmp_path, monkeypatch, name="demo", requirement="build value") -> Path:
    """DB row + run.yaml + flow events + recorder events. Returns workspace."""
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)
    init_db()
    workspace = tmp_path / f"ws-{name}"
    workspace.mkdir()
    project = Project(name=name, mode=ProjectMode.GREENFIELD, workspace_path=str(workspace))
    project.requirement = requirement
    insert_project(project)
    run = HarnessRun(
        id="h-1", project_name=name, workspace=str(workspace),
        mode="greenfield", original_goal=requirement,
        options=HarnessOptions(max_rounds=4),
        greenfield_run=GreenfieldRun(
            id="gf-1", project_name=name, requirement=requirement,
            workspace=str(workspace), options=GreenfieldOptions(),
        ),
        stop_state={"reason": "goals_satisfied", "evidence": {"iteration": 2}},
    )
    save_harness_run(run)
    events_path = workspace / ".onep" / "harness" / "flow-events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    for stage in ("understand", "build", "stop"):
        events_path.write_text(
            (events_path.read_text(encoding="utf-8") if events_path.exists() else "")
            + json.dumps({"type": "flow_transition",
                          "payload": {"stage": stage, "iteration": 1 if stage != "stop" else 2}})
            + "\n", encoding="utf-8")
    run_dir = workspace / ".onep" / "greenfield" / "runs" / "gf-1"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps({"type": "trace", "stage": "BUILD", "round": 1,
                    "payload": {"label": "SLICE", "message": "core ok"}}) + "\n" +
        json.dumps({"type": "trace", "stage": "BUILD", "round": 1,
                    "payload": {"label": "SLICE", "message": "more ok"}}) + "\n",
        encoding="utf-8")
    return workspace


def seed_vault(workspace: Path, tmp_path, monkeypatch) -> dict[str, Path]:
    """Project vault (MOC + event note) + global vault (one article). Returns roots."""
    from onep.harness.vault import VaultWriter
    project_root = workspace / ".onep" / "knowledge"
    global_root = tmp_path / "global-vault"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"knowledge": {"vault_root": str(global_root)}}),
        encoding="utf-8")
    monkeypatch.setattr("onep.harness.vault._config_path", lambda: config_path)
    writer = VaultWriter(global_root, project_root=project_root)
    writer.write_project_moc("demo", "build value", "running", [])
    writer.write_event_note(
        event={"type": "experiment", "stage": "BUILD", "round": 1,
               "evidence": "all tests pass",
               "payload": {"title": "Test Results", "candidates": []}},
        project="demo", iteration=1)
    writer.write_note(
        "Engineering/Articles", "demo",
        {"title": "Demo Journey", "project": "demo", "type": "article",
         "created": "2026-08-17T00:00:00Z", "tags": [], "related": []},
        "A summary of the demo run.")
    return {"project": project_root, "global": global_root}
