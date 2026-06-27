"""Filesystem tools compatible with CrewAI agents."""
from __future__ import annotations

from pathlib import Path

from crewai.tools import BaseTool


class FileReadTool(BaseTool):
    name: str = "file_read"
    description: str = "Read the contents of a file within the workspace."

    workspace: str = ""

    def _run(self, path: str) -> str:
        full = (Path(self.workspace) / path).resolve()
        if not str(full).startswith(str(Path(self.workspace).resolve())):
            return f"Error: path '{path}' is outside workspace"
        if not full.exists():
            return f"Error: file not found: {path}"
        return full.read_text()


class FileWriteTool(BaseTool):
    name: str = "file_write"
    description: str = "Write content to a file within the workspace. Creates parent directories as needed."

    workspace: str = ""

    def _run(self, path: str, content: str) -> str:
        full = (Path(self.workspace) / path).resolve()
        if not str(full).startswith(str(Path(self.workspace).resolve())):
            return f"Error: path '{path}' is outside workspace"
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return f"Written: {path}"


class FileListTool(BaseTool):
    name: str = "file_list"
    description: str = "List files and directories within a workspace subdirectory."

    workspace: str = ""

    def _run(self, path: str = ".") -> str:
        full = (Path(self.workspace) / path).resolve()
        if not str(full).startswith(str(Path(self.workspace).resolve())):
            return f"Error: path '{path}' is outside workspace"
        if not full.exists():
            return f"Error: directory not found: {path}"
        items = sorted(full.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        lines = []
        for p in items:
            suffix = "/" if p.is_dir() else ""
            lines.append(f"  {p.name}{suffix}")
        return f"{path}/\n" + "\n".join(lines) if lines else f"{path}/ is empty"
