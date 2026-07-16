"""Filesystem tools compatible with CrewAI agents."""
from __future__ import annotations

from pathlib import Path

from crewai.tools import BaseTool
from onep.runtime.environment import LocalWorktreeEnvironment


class FileReadTool(BaseTool):
    name: str = "file_read"
    description: str = "Read the contents of a file within the workspace."

    workspace: str = ""

    def _run(self, path: str) -> str:
        try:
            return LocalWorktreeEnvironment(self.workspace).read_text(path)
        except ValueError:
            return f"Error: path '{path}' is outside workspace"
        except FileNotFoundError:
            return f"Error: file not found: {path}"


class FileWriteTool(BaseTool):
    name: str = "file_write"
    description: str = "Write content to a file within the workspace. Creates parent directories as needed."

    workspace: str = ""

    def _run(self, path: str, content: str) -> str:
        try:
            LocalWorktreeEnvironment(self.workspace).write_text(path, content)
        except ValueError:
            return f"Error: path '{path}' is outside workspace"
        return f"Written: {path}"


class FileListTool(BaseTool):
    name: str = "file_list"
    description: str = "List files and directories within a workspace subdirectory."

    workspace: str = ""

    def _run(self, path: str = ".") -> str:
        try:
            items = LocalWorktreeEnvironment(self.workspace).list_entries(path)
        except ValueError:
            return f"Error: path '{path}' is outside workspace"
        except FileNotFoundError:
            return f"Error: directory not found: {path}"
        lines = []
        for p in items:
            suffix = "/" if p.is_dir() else ""
            lines.append(f"  {p.name}{suffix}")
        return f"{path}/\n" + "\n".join(lines) if lines else f"{path}/ is empty"
