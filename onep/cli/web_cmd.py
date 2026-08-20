"""onep web — run the local web console (no authentication)."""
from __future__ import annotations

import click
import subprocess
import sys


@click.command(name="web")
@click.option("--host", default=None,
              help="Bind address (default: config.yaml web.host, else 127.0.0.1)")
@click.option("--port", type=click.IntRange(1, 65535), default=None,
              help="Port (default: config.yaml web.port, else 8311)")
def web_cmd(host: str | None, port: int | None):
    """Run the local web console (no authentication; binds 127.0.0.1 by default)."""
    from onep.application.defaults import control_store_path
    from onep.web.runtime import web_config
    from onep.web.server import run_server

    resolved_host = host or web_config()[0]
    if resolved_host not in {"127.0.0.1", "localhost", "::1"}:
        raise click.ClickException(
            "Remote binding is disabled until authentication is configured."
        )
    worker = subprocess.Popen([
        sys.executable,
        "-m",
        "onep.execution.runner",
        "--db",
        str(control_store_path()),
    ])
    try:
        run_server(host=host, port=port)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()


COMMANDS = [web_cmd]
