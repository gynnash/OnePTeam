from types import SimpleNamespace

from onep.tools import lint
from onep.tools.lint import LintTool


def test_lint_tool_uses_ruff_default_supported_output_format(monkeypatch, tmp_path):
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="All checks passed!\n", stderr="")

    monkeypatch.setattr(lint.subprocess, "run", run)

    output = LintTool(workspace=str(tmp_path))._run("src")

    assert captured["command"] == ["ruff", "check", "src"]
    assert "No issues found" in output
