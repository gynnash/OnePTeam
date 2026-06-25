"""Tests for ShellTool."""
from pathlib import Path

import pytest

from onep.tools.shell import ShellTool


def test_shell_echo(tmp_path: Path):
    tool = ShellTool(workspace=str(tmp_path))
    result = tool.run(command="echo hello")
    assert "hello" in result


def test_shell_directory_scoped(tmp_path: Path):
    (tmp_path / "subdir").mkdir()
    tool = ShellTool(workspace=str(tmp_path))
    result = tool.run(command="pwd")
    assert str(tmp_path) in result
