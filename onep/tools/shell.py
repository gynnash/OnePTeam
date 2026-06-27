"""Shell command execution compatible with CrewAI agents."""
from __future__ import annotations

import os
import re
import subprocess

from crewai.tools import BaseTool

# Patterns that match potentially destructive commands
_DENY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\brm\s.*-r\S*f\b'),       'rm -rf (force recursive delete)'),
    (re.compile(r'\brm\s.*--recursive'),     'rm --recursive'),
    (re.compile(r'\bgit\s+push\s.*--force'), 'git push --force'),
    (re.compile(r'\bgit\s+push\s.*-f\b'),    'git push -f'),
    (re.compile(r'\bgit\s+reset\s+--hard'),  'git reset --hard'),
    (re.compile(r'\bgit\s+clean\s+-f'),      'git clean -f'),
    (re.compile(r'\bsudo\b'),                'sudo (privilege escalation)'),
    (re.compile(r'\bchmod\b'),               'chmod (permission change)'),
    (re.compile(r'\bchown\b'),               'chown (ownership change)'),
    (re.compile(r'\bmkfs\.'),                'mkfs (format filesystem)'),
    (re.compile(r'\bdd\s+if='),              'dd (raw disk write)'),
    (re.compile(r'>\s*/dev/'),               'redirect to /dev/ device'),
    (re.compile(r'\bshutdown\b'),            'shutdown'),
    (re.compile(r'\breboot\b'),              'reboot'),
    (re.compile(r'\bkill\s+-9\b'),           'kill -9 (force kill)'),
    (re.compile(r':\(\)\s*\{'),              'fork bomb pattern'),
    (re.compile(r'\bcurl.*\|\s*(ba)?sh'),    'curl pipe shell (remote code exec)'),
    (re.compile(r'\bwget.*\|\s*(ba)?sh'),    'wget pipe shell (remote code exec)'),
]


class ShellTool(BaseTool):
    name: str = "shell"
    description: str = (
        "Execute a shell command in the workspace directory. "
        "Destructive commands (rm -rf, git push --force, sudo, etc.) are blocked."
    )

    workspace: str = ""

    def _run(self, command: str, timeout: int = 120) -> str:
        """Execute a shell command.

        Args:
            command: The shell command to run
            timeout: Timeout in seconds (default 120)
        """
        deny_reason = _check_command(command)
        if deny_reason:
            return (
                f"Blocked: command matches dangerous pattern '{deny_reason}'.\n"
                "This operation is not allowed for safety reasons."
            )

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
            out = result.stdout
            if result.stderr:
                out += "\n[stderr]\n" + result.stderr
            if result.returncode != 0:
                out += f"\n[exit: {result.returncode}]"
            return out or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {command}"


def _check_command(command: str) -> str | None:
    """Return the denial reason if command matches any dangerous pattern, else None."""
    cmd_lower = command.lower()
    for pattern, label in _DENY_PATTERNS:
        if pattern.search(command) or pattern.search(cmd_lower):
            return label
    return None
