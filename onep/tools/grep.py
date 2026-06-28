"""GrepTool — search for patterns in the source tree."""
from __future__ import annotations

import subprocess

from crewai.tools import BaseTool


class GrepTool(BaseTool):
    name: str = "grep"
    description: str = (
        "Search for a text pattern in source files. "
        "Returns matching file:line:content. "
        "Use this to find where a function/class/pattern is defined or referenced."
    )

    workspace: str = ""

    def _run(self, pattern: str, path: str = ".", max_results: int = 30) -> str:
        try:
            result = subprocess.run(
                ["grep", "-rn", "--include=*.py", "--include=*.ts",
                 "--include=*.tsx", "--include=*.js", "--include=*.jsx",
                 "--include=*.md", "--include=*.yaml", "--include=*.yml",
                 "--include=*.toml", "--include=*.json",
                 pattern, path],
                capture_output=True, text=True, timeout=15,
                cwd=self.workspace,
            )
            lines = result.stdout.rstrip("\n").split("\n")
            if not lines or lines == [""]:
                return "(no matches)"
            if len(lines) > max_results:
                shown = lines[:max_results]
                return "\n".join(shown) + f"\n... ({len(lines) - max_results} more matches)"
            return "\n".join(lines)
        except subprocess.TimeoutExpired:
            return f"Search timed out for pattern: {pattern}"
        except FileNotFoundError:
            return "grep not available"
