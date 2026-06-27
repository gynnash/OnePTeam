"""Tests for filesystem tools."""
from pathlib import Path

import pytest

from onep.tools.filesystem import FileReadTool, FileWriteTool, FileListTool


def test_write_and_read(tmp_path: Path):
    ws = str(tmp_path)
    writer = FileWriteTool(workspace=ws)
    reader = FileReadTool(workspace=ws)

    writer.run(path="test.txt", content="hello world")
    content = reader.run(path="test.txt")
    assert content == "hello world"


def test_path_traversal_blocked(tmp_path: Path):
    ws = str(tmp_path)
    writer = FileWriteTool(workspace=ws)
    result = writer.run(path="../outside.txt", content="escape")
    assert "outside workspace" in result


def test_list_dir(tmp_path: Path):
    ws = str(tmp_path)
    writer = FileWriteTool(workspace=ws)
    lister = FileListTool(workspace=ws)

    writer.run(path="a.txt", content="a")
    writer.run(path="b.txt", content="b")

    files = lister.run(path=".")
    assert "a.txt" in files
    assert "b.txt" in files
