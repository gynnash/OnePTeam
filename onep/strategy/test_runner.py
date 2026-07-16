"""Run Plan test commands and trust process exit codes."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from onep.strategy.optimize_models import TestCommandResult
from onep.runtime.environment import LocalWorktreeEnvironment


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
        environment = LocalWorktreeEnvironment(worktree)
        for command in commands:
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat()
            execution = environment.run(command, self.timeout)
            result = TestCommandResult(
                command=command,
                exit_code=execution.exit_code,
                stdout=execution.stdout,
                stderr=execution.stderr,
                duration_seconds=time.monotonic() - started,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                timed_out=execution.timed_out,
            )
            results.append(result)
            if not result.passed:
                break
        return PlanTestResult(results)
