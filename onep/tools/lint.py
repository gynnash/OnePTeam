"""Code linting compatible with CrewAI agents."""
from __future__ import annotations

import subprocess

from crewai.tools import BaseTool


class LintTool(BaseTool):
    name: str = "lint"
    description: str = "Run ruff lint checks on Python code in the workspace."

    workspace: str = ""

    def _run(self, path: str = ".") -> str:
        """Run ruff linter on the given path.

        Args:
            path: Relative path within workspace to lint (default: entire workspace)
        """
        try:
            result = subprocess.run(
                ["ruff", "check", path, "--output-format=text"],
                capture_output=True, text=True, cwd=self.workspace, timeout=60,
            )
            if result.returncode == 0:
                return "No issues found.\n" + (result.stdout or "")
            return (result.stdout + "\n" + result.stderr) or "Lint issues found."
        except FileNotFoundError:
            return "Lint skipped: ruff not installed."
