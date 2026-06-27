"""Git operations compatible with CrewAI agents."""
from __future__ import annotations

import git
from crewai.tools import BaseTool


class GitTool(BaseTool):
    name: str = "git"
    description: str = "Run git operations: status, log, diff, commit. Workspace must be a git repository."

    workspace: str = ""

    def _run(self, operation: str, message: str = "", paths: str = ".") -> str:
        """Run a git operation.

        Args:
            operation: One of status, log, diff, commit, add
            message: Commit message (required for commit)
            paths: File paths to stage (for add/commit)
        """
        repo = git.Repo(self.workspace)
        op = operation.lower()

        if op == "status":
            return repo.git.status()

        if op == "log":
            commits = list(repo.iter_commits(max_count=10))
            lines = [f"{c.hexsha[:8]} {c.message.split(chr(10))[0]}" for c in commits]
            return "\n".join(lines) if lines else "(no commits)"

        if op == "diff":
            return repo.git.diff() or "(no changes)"

        if op == "add":
            repo.index.add([p.strip() for p in paths.split(",")])
            return f"Staged: {paths}"

        if op == "commit":
            if not message:
                return "Error: commit requires a message"
            commit = repo.index.commit(message)
            return f"Commit: {commit.hexsha[:8]} - {message}"

        return f"Unknown operation: {operation}. Available: status, log, diff, commit, add"
