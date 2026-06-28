"""Run Plan test commands and trust process exit codes."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from onep.strategy.optimize_models import TestCommandResult


@dataclass
class PlanTestResult:
    commands: list[TestCommandResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.commands) and all(command.passed for command in self.commands)


class PlanTestRunner:
    def __init__(self, timeout: float = 600):
        self.timeout = timeout

    def run(self, worktree: Path, commands: list[str]) -> PlanTestResult:
        results: list[TestCommandResult] = []
        for command in commands:
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat()
            try:
                process = subprocess.run(
                    ["/bin/sh", "-lc", command],
                    cwd=worktree,
                    timeout=self.timeout,
                    capture_output=True,
                    text=True,
                )
                result = TestCommandResult(
                    command=command,
                    exit_code=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    duration_seconds=time.monotonic() - started,
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(),
                )
            except subprocess.TimeoutExpired as exc:
                result = TestCommandResult(
                    command=command,
                    exit_code=124,
                    stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                    stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                    duration_seconds=time.monotonic() - started,
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(),
                    timed_out=True,
                )
            results.append(result)
            if not result.passed:
                break
        return PlanTestResult(results)
