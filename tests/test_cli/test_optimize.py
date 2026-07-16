from click.testing import CliRunner
from types import SimpleNamespace
import git

from onep.cli.optimize_cmd import optimize_cmd


def test_optimize_help():
    runner = CliRunner()
    result = runner.invoke(optimize_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--max-rounds" in result.output
    assert "--auto-approve" in result.output
    assert "--max-cost" in result.output


def test_optimize_requires_explicit_gate_before_creating_worktree(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    repo = git.Repo.init(source)
    with repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (source / "app.txt").write_text("no manifest\n")
    repo.index.add(["app.txt"])
    repo.index.commit("initial")
    created = []

    class Session:
        def __init__(self, *args):
            created.append(args)

    monkeypatch.setattr(
        "onep.cli.optimize_cmd.load_config",
        lambda: SimpleNamespace(
            project=SimpleNamespace(root_dir=str(tmp_path / "onep"))
        ),
    )
    monkeypatch.setattr("onep.cli.optimize_cmd.GitRunSession", Session)
    result = CliRunner().invoke(optimize_cmd, [str(source)])
    assert result.exit_code != 0
    assert "pass --test-command" in result.output
    assert created == []
