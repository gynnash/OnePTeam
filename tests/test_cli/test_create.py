from click.testing import CliRunner
import git

from onep.cli.create import create_project, default_project_name
from onep.main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "OnePTeam" in result.output


def test_create_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["create", "--help"])
    assert result.exit_code == 0


def test_create_initializes_git_repository(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.application.projects.init_db", lambda: None)
    monkeypatch.setattr(
        "onep.application.projects.insert_project", lambda project: None
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli, ["create", "A test application", "--name", "test-app", "--no-run"]
    )

    workspace = tmp_path
    assert result.exit_code == 0
    assert "Project 'test-app' created" in result.output
    repo = git.Repo(workspace)
    assert repo.head.commit.message == "chore: initialize onep greenfield project"
    assert (workspace / "README.md").read_text() == (
        "# test-app\n\nA test application\n"
    )


def test_create_reuses_current_git_repository_and_config(tmp_path, monkeypatch):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Local User")
        config.set_value("user", "email", "local@example.com")
        config.set_value("onep", "marker", "keep-me")
    monkeypatch.setattr("onep.application.projects.init_db", lambda: None)
    inserted = []
    monkeypatch.setattr("onep.application.projects.insert_project", inserted.append)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli, ["create", "An existing repository", "--name", "existing", "--no-run"]
    )

    assert result.exit_code == 0
    assert inserted[0].workspace_path == str(tmp_path)
    reopened = git.Repo(tmp_path)
    assert reopened.config_reader().get_value("onep", "marker") == "keep-me"
    assert reopened.head.commit.message == "chore: initialize onep greenfield project"


def test_create_runs_engineering_loop_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("onep.application.projects.init_db", lambda: None)
    monkeypatch.setattr(
        "onep.application.projects.insert_project", lambda project: None
    )
    called = []
    monkeypatch.setattr(
        "onep.orchestrator.runner.run_pipeline",
        lambda name, options=None: called.append((name, options)) or True,
    )

    result = CliRunner().invoke(
        cli, ["create", "Automatic app", "--name", "auto"]
    )

    assert result.exit_code == 0
    assert called[0][0] == "auto"
    assert called[0][1].max_rounds == 100
    assert called[0][1].max_repairs_per_slice == 8


def test_create_project_function_creates_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)
    workspace = tmp_path / "ws"
    project = create_project("build a calculator", name="calc", workspace=workspace)
    assert project.name == "calc"
    assert project.workspace_path == str(workspace.resolve())
    assert (workspace / "README.md").exists()
    assert (workspace / "docs").is_dir()
    assert (workspace / ".onep" / "state.yaml").exists()


def test_create_project_default_name_from_requirement():
    assert default_project_name("Build a CLI Tool!") == "BuildaCLITool"
    assert default_project_name("")  # falls back to project-<hex>
