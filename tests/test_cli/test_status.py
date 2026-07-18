from click.testing import CliRunner
from types import SimpleNamespace

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


def test_delete_keeps_external_in_place_workspace(tmp_path, monkeypatch):
    db_dir = tmp_path / "onep-data"
    external_workspace = tmp_path / "source-repo"
    external_workspace.mkdir()
    marker = external_workspace / "keep.txt"
    marker.write_text("keep")
    monkeypatch.setattr(
        "onep.persistence.database._config_dir", lambda: db_dir
    )
    monkeypatch.setattr(
        "onep.cli.status.load_config",
        lambda: SimpleNamespace(
            project=SimpleNamespace(root_dir=str(db_dir))
        ),
    )
    init_db()
    insert_project(Project(
        name="external",
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(external_workspace),
    ))

    result = CliRunner().invoke(cli, ["delete", "external", "--force"])

    assert result.exit_code == 0
    assert "Kept external workspace" in result.output
    assert marker.read_text() == "keep"
