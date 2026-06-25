"""Git operations via GitPython."""
from __future__ import annotations

from pathlib import Path
import git

from onep.tools.base import BaseTool


class GitTool(BaseTool):
    name = "git"
    description = "Git operations scoped to a workspace."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def _repo(self) -> git.Repo:
        return git.Repo(str(self.workspace))

    def init(self) -> str:
        repo = git.Repo.init(str(self.workspace))
        return str(repo.working_dir)

    def add(self, paths: list[str]) -> str:
        repo = self._repo()
        repo.index.add(paths)
        return f"Staged: {paths}"

    def commit(self, message: str) -> str:
        repo = self._repo()
        commit = repo.index.commit(message)
        return f"Commit: {commit.hexsha[:8]} - {message}"

    def status(self) -> str:
        repo = self._repo()
        return repo.git.status()

    def log(self, max_count: int = 10) -> str:
        repo = self._repo()
        commits = list(repo.iter_commits(max_count=max_count))
        return "\n".join(f"{c.hexsha[:8]} {c.message.split(chr(10))[0]}" for c in commits)

    def run(self, **kwargs):
        operation = kwargs.get("operation", "status")
        if operation == "init":
            return self.init()
        elif operation == "add":
            return self.add(kwargs.get("paths", ["."]))
        elif operation == "commit":
            return self.commit(kwargs["message"])
        elif operation == "status":
            return self.status()
        elif operation == "log":
            return self.log()
        raise ValueError(f"Unknown operation: {operation}")
