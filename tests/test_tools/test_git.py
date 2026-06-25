"""Tests for GitTool."""
from pathlib import Path

import pytest

from onep.tools.git import GitTool


def test_git_init_and_status(tmp_path: Path):
    tool = GitTool(workspace=tmp_path)
    result = tool.init()
    assert tmp_path.name in str(result) or "git" in str(result).lower()

    status = tool.status()
    assert "No commits yet" in status or "On branch" in status


def test_git_add_and_commit(tmp_path: Path):
    tool = GitTool(workspace=tmp_path)
    tool.init()

    (tmp_path / "test.txt").write_text("hello")
    tool.add(["test.txt"])
    result = tool.commit("initial commit")
    assert "initial commit" in result

    log = tool.log(max_count=1)
    assert "initial commit" in log
