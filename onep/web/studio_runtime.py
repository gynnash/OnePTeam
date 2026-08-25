"""Small runtime configuration surface for the v2 local Web application."""

from __future__ import annotations

from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8311


def _config_path() -> Path:
    return Path.home() / ".onep" / "config.yaml"


def web_config() -> tuple[str, int]:
    """Read the optional local Web bind address without old runtime imports."""
    try:
        import yaml

        raw = yaml.safe_load(_config_path().read_text(encoding="utf-8")) or {}
        web = raw.get("web") or {}
        host = str(web.get("host") or DEFAULT_HOST)
        port = int(web.get("port") or DEFAULT_PORT)
    except (OSError, yaml.YAMLError, ValueError, TypeError):
        host, port = DEFAULT_HOST, DEFAULT_PORT
    return host, port
