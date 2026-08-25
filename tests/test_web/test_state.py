import json
from pathlib import Path

from onep.domain import Job, JobStatus
from onep.harness.models import (
    HarnessRun,
    HarnessOptions,
    QualitySnapshot,
    ImprovementCandidate,
)
from onep.harness.persistence import load_harness_run, save_harness_run
from onep.persistence.models import Project, ProjectMode
from onep.web.state import (
    flow_events_path,
    last_flow_stage,
    log_entries,
    project_summaries,
    resolve_run_dir,
    run_detail,
    run_summary,
    stage_history,
)

from tests.test_web.fixtures import seed_project


def test_last_flow_stage_returns_tail(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    assert last_flow_stage(workspace) == "stop"


def test_last_flow_stage_empty_without_file(tmp_path):
    assert last_flow_stage(tmp_path / "nope") == ""


def test_stage_history(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    history = stage_history(workspace)
    assert [entry["stage"] for entry in history] == ["understand", "build", "stop"]
    assert all(entry["type"] == "flow_transition" for entry in history)


def test_run_summary(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    summary = run_summary(workspace)
    assert summary["project_name"] == "demo"
    assert summary["mode"] == "greenfield"
    assert summary["stage"] == "stop"
    assert summary["iteration"] == 0
    assert summary["stop_reason"] == "goals_satisfied"
    assert run_summary(tmp_path / "nope") is None


def test_project_summaries(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    rows = project_summaries()
    assert len(rows) == 1
    assert rows[0]["name"] == "demo"
    assert rows[0]["harness"]["project_name"] == "demo"


def test_brownfield_summary_uses_owning_workflow_job_status(tmp_path):
    project = Project(
        id="project-1",
        name="daily_stock_analysis",
        mode=ProjectMode.BROWNFIELD,
        workspace_path=str(tmp_path / "workspace"),
        requirement="优化交互",
        created_at="2026-08-23T03:56:29+00:00",
        updated_at="2026-08-23T03:56:29+00:00",
    )
    job = Job(
        id="job-1",
        capability_id="optimization.start",
        payload={
            "source": "/workspace/daily_stock_analysis",
            "goal": "优化交互",
        },
        status=JobStatus.FAILED,
        created_at="2026-08-23T03:56:27+00:00",
        updated_at="2026-08-23T04:02:00+00:00",
    )

    row = project_summaries([project], jobs=[job])[0]

    assert row["status"] == "failed"
    assert row["current_stage"] == "failed"
    assert row["updated_at"] == job.updated_at
    assert row["workflow_job"] == {
        "id": "job-1",
        "capability_id": "optimization.start",
        "status": "failed",
    }


def test_run_detail_shape(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    detail = run_detail(workspace)
    assert detail["original_goal"] == "build value"
    assert detail["stages"] == [
        "init",
        "understand",
        "research",
        "design",
        "plan",
        "build",
        "verify",
        "review",
        "reflect",
        "discover",
        "prioritize",
        "stop",
        "failed",
        "cancelled",
    ]
    assert detail["stop_state"]["reason"] == "goals_satisfied"
    assert detail["stage_history"][-1]["stage"] == "stop"
    assert detail["quality_history"] == []
    assert detail["improvement_candidates"] == []
    assert run_detail(tmp_path / "nope") is None


def test_resolve_run_dir_greenfield(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    assert (
        resolve_run_dir(workspace)
        == workspace / ".onep" / "greenfield" / "runs" / "gf-1"
    )
    assert resolve_run_dir(tmp_path / "nope") is None


def test_resolve_run_dir_mixed_uses_greenfield_backend(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    run = load_harness_run(workspace)
    run.mode = "mixed"
    save_harness_run(run)
    assert resolve_run_dir(workspace) == (
        workspace / ".onep" / "greenfield" / "runs" / "gf-1"
    )


def test_log_entries_offset_and_limit(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    entries = log_entries(workspace, offset=1, limit=1)
    assert len(entries) == 1
    assert entries[0]["offset"] == 1
    assert entries[0]["type"] == "trace"
    assert entries[0]["payload"]["label"] == "SLICE"
    assert log_entries(tmp_path / "nope") == []


def test_last_flow_stage_skips_non_dict_lines(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    flow_path = flow_events_path(workspace)
    flow_path.write_text(
        '"just a string"\n'
        "42\n"
        '{"type": "flow_transition", "payload": "oops"}\n'
        '{"type": "flow_transition", "payload": {"stage": "build", "iteration": 2}}\n'
    )
    assert last_flow_stage(workspace) == "build"


def test_stage_history_skips_non_dict_payloads(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    flow_events_path(workspace).write_text(
        '{"type": "flow_transition", "payload": {"stage": "understand", "iteration": 1}}\n'
        '{"type": "flow_transition", "payload": 42}\n'
        '{"type": "flow_transition", "payload": {"stage": "stop", "iteration": 1}}\n'
    )
    assert [entry["stage"] for entry in stage_history(workspace)] == [
        "understand",
        "stop",
    ]
