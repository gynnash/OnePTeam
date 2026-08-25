"""Settings boundary for the direct-cutover Product Studio runtime."""

from __future__ import annotations

from typing import Any

from onep.config import load_config


def runtime_connection_test(
    payload: dict[str, Any] | None = None, _context=None
) -> dict[str, Any]:
    """Probe the required engineering backend in isolation."""
    from onep.runtime.codex_app_server import CodexAppServerRuntime

    del payload, _context
    runtime = CodexAppServerRuntime(load_config().execution)
    try:
        return runtime.probe().to_dict()
    finally:
        runtime.close()
