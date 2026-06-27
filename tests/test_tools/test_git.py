"""Tests for GitTool."""
from pathlib import Path
import subprocess

import pytest

from onep.tools.git import GitTool


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True, capture_output=True)


def test_git_add_and_commit(tmp_path: Path):
    _init_repo(tmp_path)

    (tmp_path / "test.txt").write_text("hello")
    tool = GitTool(workspace=str(tmp_path))

    result = tool.run(operation="add", paths="test.txt")
    assert "test.txt" in result

    result = tool.run(operation="commit", message="initial commit")
    assert "initial commit" in result

    log = tool.run(operation="log")
    assert "initial commit" in log


def test_git_status(tmp_path: Path):
    _init_repo(tmp_path)
    tool = GitTool(workspace=str(tmp_path))
    status = tool.run(operation="status")
    assert "On branch" in status or "No commits" in status
