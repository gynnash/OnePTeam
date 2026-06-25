"""Basic code quality checks."""
from __future__ import annotations

import subprocess
from pathlib import Path

from onep.tools.base import BaseTool


class LintTool(BaseTool):
    name = "lint"
    description = "Run linting and basic code quality checks."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def check_python(self, path: str = ".") -> str:
        """Run ruff or flake8 on Python files."""
        try:
            result = subprocess.run(
                ["ruff", "check", path, "--output-format=text"],
                capture_output=True, text=True, cwd=str(self.workspace), timeout=60,
            )
            if result.returncode == 0:
                return "No issues found.\n" + result.stdout
            return result.stdout + "\n" + result.stderr
        except FileNotFoundError:
            return "Lint skipped: ruff not installed."

    def run(self, **kwargs):
        language = kwargs.get("language", "python")
        path = kwargs.get("path", ".")
        if language == "python":
            return self.check_python(path)
        return f"Lint not supported for: {language}"
