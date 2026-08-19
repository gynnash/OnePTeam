"""Runtime helpers shared by the server, the API routers, and the CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from onep.harness.persistence import harness_run_path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8311
POLL_INTERVAL = 1.0
HEARTBEAT_INTERVAL = 15.0
# Consecutive empty poll cycles after which the stream closes itself. With the
# default heartbeat interval (15s) heartbeats reset the counter, so the stream
# stays open indefinitely; the bound only terminates streams whose heartbeat
# interval is large or disabled (e.g. tests), where an endless stream could
# never be closed by the client.
MAX_EMPTY_POLLS = 500

_RUN_ENTRY = (
    "import sys; "
    "from onep.orchestrator.runner import run_pipeline; "
    "sys.exit(0 if run_pipeline(sys.argv[1]) else 1)"
)


def _config_path() -> Path:
    return Path.home() / ".onep" / "config.yaml"


def web_config() -> tuple[str, int]:
    """(host, port) from config.yaml web: section; tolerant of missing config."""
    try:
        import yaml

        raw = yaml.safe_load(_config_path().read_text(encoding="utf-8")) or {}
        web = raw.get("web") or {}
        host = str(web.get("host") or DEFAULT_HOST)
        port = int(web.get("port") or DEFAULT_PORT)
    except (OSError, yaml.YAMLError, ValueError, TypeError):
        host, port = DEFAULT_HOST, DEFAULT_PORT
    return host, port


def managed_root() -> Path:
    from onep.config import load_config

    return Path(load_config().project.root_dir).expanduser() / "projects"


def workspace_for(name: str) -> Path:
    root = managed_root()
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"project name escapes the managed root: {name!r}")
    return resolved


def spawn_run(name: str, workspace: Path) -> dict[str, Any] | None:
    """Start `onep run <name>` in a detached subprocess; None on failure.

    Child stdout/stderr are appended to `<workspace>/.onep/web-run.log` so the
    pipe buffer can never fill and stall the harness.
    """
    log_path = Path(workspace) / ".onep" / "web-run.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "a", encoding="utf-8")
    except OSError:
        return None
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", _RUN_ENTRY, name],
            cwd=str(workspace),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError:
        log_handle.close()
        return None
    # Popen dups the fd into the child; the parent copy can be closed now.
    log_handle.close()
    return {"pid": process.pid, "started": True}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _fingerprint(path: Path):
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def event_stream(workspace, poll: float = POLL_INTERVAL, max_events: int | None = None):
    """Yield SSE events by tailing harness state files.

    flow-events.jsonl -> "flow", recorder events.jsonl -> "log",
    distillations.jsonl -> "distill", run.yaml changes -> "state".

    The stream terminates after MAX_EMPTY_POLLS consecutive poll cycles that
    produced no event (state change, tailed line, or heartbeat); heartbeats
    and events reset the counter.
    """
    from onep.web import state as harness_state

    flow_path = harness_state.flow_events_path(workspace)
    run_yaml = harness_run_path(workspace)
    run_dir = harness_state.resolve_run_dir(workspace)
    tail_paths = [
        (flow_path, "flow"),
        (run_dir / "events.jsonl" if run_dir else None, "log"),
        (run_dir / "distillations.jsonl" if run_dir else None, "distill"),
    ]
    cursors: dict[str, int] = {}
    for path, _ in tail_paths:
        if path and path.exists():
            cursors[str(path)] = path.stat().st_size
    run_fp = _fingerprint(run_yaml)
    emitted = 0
    last_beat = time.monotonic()
    empty_polls = 0
    while max_events is None or emitted < max_events:
        cycle_start = emitted
        resolved_run_dir = harness_state.resolve_run_dir(workspace)
        if resolved_run_dir != run_dir:
            run_dir = resolved_run_dir
            tail_paths = [
                (flow_path, "flow"),
                (run_dir / "events.jsonl" if run_dir else None, "log"),
                (run_dir / "distillations.jsonl" if run_dir else None, "distill"),
            ]
        new_run_fp = _fingerprint(run_yaml)
        if new_run_fp != run_fp:
            run_fp = new_run_fp
            summary = harness_state.run_summary(workspace)
            if summary:
                yield format_sse({"type": "state", "payload": summary})
                emitted += 1
        for path, kind in tail_paths:
            if path is None or not path.exists():
                continue
            size = path.stat().st_size
            key = str(path)
            if size < cursors.get(key, 0):
                cursors[key] = 0
            if size > cursors.get(key, 0):
                with open(path, encoding="utf-8") as handle:
                    handle.seek(cursors.get(key, 0))
                    content = handle.read()
                    cursors[key] = handle.tell()
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue
                    if kind == "flow":
                        # flow_transition rows are envelopes around the stage
                        # payload; mirror state.last_flow_stage/stage_history.
                        payload = raw.get("payload")
                        if not isinstance(payload, dict):
                            continue
                    else:
                        # Recorder/log and distill rows carry their metadata at
                        # the top level (stage, round, timestamp) — keep rows.
                        payload = raw
                    yield format_sse({"type": kind, "payload": payload})
                    emitted += 1
        now = time.monotonic()
        if now - last_beat >= HEARTBEAT_INTERVAL:
            last_beat = now
            yield format_sse({"type": "heartbeat", "payload": {"at": _now()}})
            emitted += 1
        time.sleep(poll)
        if emitted > cycle_start:
            empty_polls = 0
        else:
            empty_polls += 1
            if empty_polls > MAX_EMPTY_POLLS:
                return
