from click.testing import CliRunner

from onep.main import cli
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.harness.models import HarnessRun
from onep.harness.persistence import save_harness_run


def _run_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.persistence.database._config_dir", lambda: tmp_path)
    init_db()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    insert_project(Project(
        name="demo", mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace), requirement="build value",
    ))
    run = HarnessRun(
        id="h-1", project_name="demo", workspace=str(workspace),
        mode="greenfield", original_goal="build value",
    )
    save_harness_run(run)
    return workspace


def test_article_command_synthesizes(tmp_path, monkeypatch):
    _run_fixture(tmp_path, monkeypatch)

    class FakeSynthesizer:
        def __init__(self, llm, writer):
            self.llm = llm
            self.writer = writer

        def synthesize(self, workspace, run_dir, run, tracker=None):
            return {
                "article_path": "/tmp/demo-article.md",
                "graph_path": "/tmp/demo-article.graph.json",
                "title": "Demo Journey",
                "markdown": "# Demo Journey",
                "graph": {},
            }

    monkeypatch.setattr("onep.cli.article_cmd.ArticleSynthesizer",
                        FakeSynthesizer)
    monkeypatch.setattr("onep.cli.article_cmd.LLMAdapter", lambda: object())
    runner = CliRunner()
    result = runner.invoke(cli, ["article", "demo"])
    assert result.exit_code == 0
    assert "demo-article.md" in result.output
    assert "Demo Journey" in result.output


def test_article_command_unknown_project(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.persistence.database._config_dir", lambda: tmp_path)
    init_db()
    runner = CliRunner()
    result = runner.invoke(cli, ["article", "ghost"])
    assert result.exit_code == 0
    assert "not found" in result.output
