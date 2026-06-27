from click.testing import CliRunner

from onep.main import cli
from onep.persistence.database import init_db, insert_project, insert_stage_run
from onep.persistence.models import (
    Project, ProjectMode, PipelineState, StageRun,
)
from onep.persistence.state import save_state, load_state


def test_status_no_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.persistence.database._config_dir", lambda: tmp_path
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0


def test_show_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "--help"])
    assert result.exit_code == 0


def _approval_project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.persistence.database._config_dir", lambda: tmp_path
    )
    init_db()
    workspace = tmp_path / "workspace"
    project = Project(
        name="demo",
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace),
        current_stage="pm",
    )
    insert_project(project)
    stage_run = StageRun(project.id, "pm", "pm")
    stage_run.start()
    stage_run.complete(["docs/PRD.md"])
    insert_stage_run(stage_run)
    save_state(workspace, PipelineState(
        stages_completed=["pm"], pending_approval=True
    ))
    return project, workspace


def test_approve_records_decision(tmp_path, monkeypatch):
    project, _ = _approval_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["approve", project.name])

    assert result.exit_code == 0
    import sqlite3
    row = sqlite3.connect(tmp_path / "meta.db").execute(
        "SELECT decision FROM approvals"
    ).fetchone()
    assert row == ("approved",)


def test_reject_records_feedback_and_reopens_stage(tmp_path, monkeypatch):
    project, workspace = _approval_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli, ["reject", project.name, "Missing acceptance criteria"]
    )

    assert result.exit_code == 0
    state = load_state(workspace)
    assert "pm" not in state.stages_completed
    assert state.current_stage == "pm"
    import sqlite3
    row = sqlite3.connect(tmp_path / "meta.db").execute(
        "SELECT decision, feedback FROM approvals"
    ).fetchone()
    assert row == ("rejected", "Missing acceptance criteria")
