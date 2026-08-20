"""Background adapters for mature analysis and optimization workflows."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import subprocess
import sys
from typing import Any

from onep.domain import Problem


def analysis_handler(store):
    def run(payload, context) -> dict[str, Any]:
        source = str(payload.get("source") or "").strip()
        if not source:
            raise Problem("source_required", "Source is required")
        command = [sys.executable, "-m", "onep.main", "analyze", source,
                   "--mode", str(payload.get("mode") or "strategy"),
                   "--no-dialogue"]
        _option(command, "--name", payload.get("name"))
        _option(command, "--max-cost", payload.get("max_cost"))
        _option(command, "--from-layer", payload.get("from_layer"))
        if payload.get("resume"):
            command.append("--resume")
        return _run(command, store, context)

    return run


def optimization_handler(store):
    def run(payload, context) -> dict[str, Any]:
        source = str(payload.get("source") or "").strip()
        if not source:
            raise Problem("source_required", "Source is required")
        path = Path(source).expanduser().resolve()
        command = [sys.executable, "-m", "onep.main", "optimize", str(path)]
        _option(command, "--name", payload.get("name"))
        _option(command, "--max-rounds", payload.get("max_rounds"))
        _option(command, "--max-cost", payload.get("max_cost"))
        _option(command, "--auto-approve", payload.get("auto_approve"))
        for value in payload.get("test_commands") or []:
            command.extend(("--test-command", str(value)))
        for value in payload.get("integration_commands") or []:
            command.extend(("--integration-test-command", str(value)))
        return _run(command, store, context, cwd=path)

    return run


def _option(command: list[str], flag: str, value) -> None:
    if value not in (None, "", 0, 0.0):
        command.extend((flag, str(value)))


def _run(command, store, context, cwd: Path | None = None) -> dict[str, Any]:
    tail: deque[str] = deque(maxlen=80)
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip()
        if not line:
            continue
        tail.append(line)
        store.append_event(
            "workflow.output",
            {"line": line[:2000], "trace_id": context.trace_id},
            project_id=context.project_id,
            run_id=context.run_id,
        )
    code = process.wait()
    if code:
        raise Problem(
            "workflow_failed",
            "Workflow failed",
            "\n".join(tail),
            actionable=True,
            suggested_actions=("inspect_debug_log", "retry"),
            trace_id=context.trace_id,
        )
    return {"exit_code": code, "summary": "\n".join(tail)}
