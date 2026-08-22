"""Background adapters for mature analysis and optimization workflows."""

from __future__ import annotations

from collections import deque
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import subprocess
import sys
from threading import Thread
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
        _option(command, "--goal", payload.get("goal"))
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
        _option(command, "--goal", payload.get("goal"))
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
        start_new_session=True,
    )
    assert process.stdout is not None
    lines: Queue[str | None] = Queue()

    def read_output() -> None:
        try:
            for raw in process.stdout:
                lines.put(raw)
        finally:
            lines.put(None)

    Thread(target=read_output, daemon=True).start()
    while True:
        job_id = str(getattr(context, "job_id", "") or "")
        if job_id and store.is_cancel_requested(job_id):
            _terminate(process)
            raise Problem(
                "workflow_cancelled",
                "Workflow cancelled",
                "The background process was stopped by user request.",
                trace_id=context.trace_id,
            )
        try:
            raw = lines.get(timeout=0.2)
        except Empty:
            continue
        if raw is None:
            break
        line = raw.rstrip()
        if line:
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


def _terminate(process) -> None:
    """Terminate the entire workflow process group, then force it if needed."""
    pid = getattr(process, "pid", None)
    try:
        if pid is not None and os.name != "nt":
            os.killpg(pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except (AttributeError, ProcessLookupError):
        return
    except subprocess.TimeoutExpired:
        if pid is not None and os.name != "nt":
            os.killpg(pid, signal.SIGKILL)
        else:
            process.kill()
