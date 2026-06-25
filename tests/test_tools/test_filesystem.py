"""Tests for FileSystemTool."""
from pathlib import Path

import pytest

from onep.tools.filesystem import FileSystemTool


@pytest.fixture
def fs_tool(tmp_path: Path):
    return FileSystemTool(workspace=tmp_path)


def test_write_and_read(fs_tool):
    fs_tool.write("test.txt", "hello world")
    content = fs_tool.read("test.txt")
    assert content == "hello world"


def test_path_traversal_blocked(fs_tool):
    with pytest.raises(ValueError):
        fs_tool.write("../outside.txt", "escape")


def test_mkdir(fs_tool):
    fs_tool.mkdir("src/components")
    assert fs_tool.exists("src/components")


def test_list_dir(fs_tool):
    fs_tool.write("a.txt", "a")
    fs_tool.write("b.txt", "b")
    files = fs_tool.list_dir(".")
    assert "a.txt" in files
    assert "b.txt" in files
