"""Safe filesystem operations scoped to the workspace directory."""
from __future__ import annotations

from pathlib import Path

from onep.tools.base import BaseTool


class FileSystemTool(BaseTool):
    name = "filesystem"
    description = "Read and write files within the workspace."

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def _validate_path(self, path: str | Path) -> Path:
        """Ensure the path is within the workspace."""
        full = (self.workspace / path).resolve()
        if not str(full).startswith(str(self.workspace)):
            raise ValueError(f"Path {path} is outside workspace")
        return full

    def read(self, path: str) -> str:
        full = self._validate_path(path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return full.read_text()

    def write(self, path: str, content: str) -> str:
        full = self._validate_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return str(full.relative_to(self.workspace))

    def mkdir(self, path: str) -> str:
        full = self._validate_path(path)
        full.mkdir(parents=True, exist_ok=True)
        return str(full.relative_to(self.workspace))

    def exists(self, path: str) -> bool:
        full = self._validate_path(path)
        return full.exists()

    def list_dir(self, path: str = ".") -> list[str]:
        full = self._validate_path(path)
        return [str(p.relative_to(self.workspace)) for p in full.iterdir()]

    def run(self, **kwargs):
        operation = kwargs.get("operation", "read")
        if operation == "read":
            return self.read(kwargs["path"])
        elif operation == "write":
            return self.write(kwargs["path"], kwargs["content"])
        elif operation == "mkdir":
            return self.mkdir(kwargs["path"])
        elif operation == "exists":
            return str(self.exists(kwargs["path"]))
        elif operation == "list":
            return "\n".join(self.list_dir(kwargs.get("path", ".")))
        raise ValueError(f"Unknown operation: {operation}")
