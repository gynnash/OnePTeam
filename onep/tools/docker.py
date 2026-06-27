"""Docker Compose operations compatible with CrewAI agents."""
from __future__ import annotations

import subprocess
import time
import urllib.request
import urllib.error

from crewai.tools import BaseTool


class DockerTool(BaseTool):
    name: str = "docker"
    description: str = "Run Docker Compose operations: up, down, ps, health."

    workspace: str = ""

    def _run(self, operation: str, url: str = "") -> str:
        """Run a Docker Compose operation.

        Args:
            operation: One of up, down, ps, health
            url: Health check URL (required for health)
        """
        cwd = self.workspace
        op = operation.lower()

        if op == "up":
            r = subprocess.run(
                ["docker", "compose", "up", "-d", "--build"],
                capture_output=True, text=True, cwd=cwd, timeout=120,
            )
            return r.stdout + r.stderr

        if op == "down":
            r = subprocess.run(
                ["docker", "compose", "down"],
                capture_output=True, text=True, cwd=cwd, timeout=60,
            )
            return r.stdout + r.stderr

        if op == "ps":
            r = subprocess.run(
                ["docker", "compose", "ps"],
                capture_output=True, text=True, cwd=cwd, timeout=30,
            )
            return r.stdout or "(no services running)"

        if op == "health":
            if not url:
                return "Error: health requires a url"
            for i in range(10):
                try:
                    urllib.request.urlopen(url, timeout=5)
                    return f"Healthy: {url} (attempt {i + 1})"
                except urllib.error.URLError:
                    time.sleep(2)
            return f"Unhealthy: {url} after 10 attempts"

        return f"Unknown operation: {operation}. Available: up, down, ps, health"
