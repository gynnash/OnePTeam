"""Docker Compose operations."""
from __future__ import annotations

import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

from onep.tools.base import BaseTool


class DockerTool(BaseTool):
    name = "docker"
    description = "Docker and Docker Compose operations."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def compose_up(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=120,
        )
        return result.stdout + result.stderr

    def compose_down(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "down"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=60,
        )
        return result.stdout + result.stderr

    def compose_ps(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "ps"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=30,
        )
        return result.stdout

    def health_check(self, url: str, retries: int = 10) -> str:
        for i in range(retries):
            try:
                urllib.request.urlopen(url, timeout=5)
                return f"Healthy: {url} (attempt {i + 1})"
            except urllib.error.URLError:
                time.sleep(2)
        return f"Unhealthy: {url} after {retries} attempts"

    def run(self, **kwargs):
        operation = kwargs.get("operation", "up")
        if operation == "up":
            return self.compose_up()
        elif operation == "down":
            return self.compose_down()
        elif operation == "ps":
            return self.compose_ps()
        elif operation == "health":
            return self.health_check(kwargs["url"])
        raise ValueError(f"Unknown operation: {operation}")
