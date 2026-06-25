"""Safe shell command execution with timeout."""
from __future__ import annotations

import subprocess
import os

from onep.tools.base import BaseTool


class ShellTool(BaseTool):
    name = "shell"
    description = "Execute shell commands within the workspace."

    def __init__(self, workspace: str, timeout: int = 300):
        self.workspace = workspace
        self.timeout = timeout

    def run(self, **kwargs):
        command = kwargs["command"]
        timeout = kwargs.get("timeout", self.timeout)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace,
                env={**os.environ},
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {command}"
