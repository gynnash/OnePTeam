"""onep web — run the local web console (no authentication)."""
from __future__ import annotations

import click


@click.command(name="web")
@click.option("--host", default=None,
              help="Bind address (default: config.yaml web.host, else 127.0.0.1)")
@click.option("--port", type=click.IntRange(1, 65535), default=None,
              help="Port (default: config.yaml web.port, else 8311)")
def web_cmd(host: str | None, port: int | None):
    """Run the local web console (no authentication; binds 127.0.0.1 by default)."""
    from onep.web.server import run_server
    run_server(host=host, port=port)


COMMANDS = [web_cmd]
