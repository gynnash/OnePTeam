"""Validated product-model and Codex settings for Product Studio."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import os
from pathlib import Path
import re
from typing import Any

from onep.config import _config_path, load_config, save_config
from onep.domain import Problem


def global_settings_read(_payload, _context) -> dict[str, Any]:
    config = load_config()
    return {
        "settings": _redacted(config),
        "revision": _file_revision(_config_path()),
        "applies_to": "next_job",
    }


def global_settings_update(store):
    def update(payload, context) -> dict[str, Any]:
        if store.has_active_jobs():
            raise Problem(
                "settings_locked_by_active_jobs", "Settings are locked",
                "Wait for queued or running jobs to finish before changing settings.",
                actionable=True,
            )
        revision = str(payload.get("revision") or "")
        if revision and revision != _file_revision(_config_path()):
            raise Problem(
                "settings_revision_conflict", "Settings changed elsewhere",
                "Reload settings before saving.", actionable=True,
            )
        patch = dict(payload.get("patch") or {})
        _reject_unknown(patch, {"llm", "execution"})
        config = load_config()
        _update_llm(config, dict(patch.get("llm") or {}))
        _update_execution(config, dict(patch.get("execution") or {}))
        save_config(config)
        return global_settings_read({}, context)

    return update


def _redacted(config) -> dict[str, Any]:
    providers = {config.llm.default_provider, config.llm.complex_provider}
    providers.update(config.llm.models)
    configured = {}
    for provider in sorted(value for value in providers if value):
        environment = bool(os.environ.get(f"{provider.upper()}_API_KEY"))
        config_value = bool((config.llm.models.get(provider) or {}).get("api_key"))
        configured[provider] = {
            "configured": environment or config_value,
            "source": (
                "environment" if environment
                else "config" if config_value else "missing"
            ),
        }
    return {
        "llm": {
            "default_model": config.llm.default_model,
            "default_provider": config.llm.default_provider,
            "complex_model": config.llm.complex_model,
            "complex_provider": config.llm.complex_provider,
            "providers": configured,
        },
        "execution": {
            **asdict(config.execution),
            "api_key_configured": bool(
                os.environ.get(config.execution.codex_api_key_env)
            ),
        },
    }


def _update_llm(config, patch: dict[str, Any]) -> None:
    allowed = {
        "default_model", "default_provider", "complex_model", "complex_provider"
    }
    _reject_unknown(patch, allowed)
    for key, value in patch.items():
        text = str(value).strip()
        if not text:
            raise Problem("invalid_settings", "Model setting cannot be empty", key)
        setattr(config.llm, key, text)


def _update_execution(config, patch: dict[str, Any]) -> None:
    allowed = {
        "codex_model", "codex_provider", "codex_auth_mode",
        "codex_api_key_env", "codex_bin", "codex_approval_policy",
        "codex_request_timeout_seconds", "codex_app_server_timeout_seconds",
    }
    _reject_unknown(patch, allowed)
    if "codex_auth_mode" in patch:
        mode = str(patch["codex_auth_mode"]).strip().lower()
        if mode not in {"existing", "api_key"}:
            raise Problem("invalid_settings", "Invalid Codex authentication mode", mode)
        config.execution.codex_auth_mode = mode
    if "codex_approval_policy" in patch:
        policy = str(patch["codex_approval_policy"]).strip()
        if policy not in {"never", "on-request", "untrusted"}:
            raise Problem("invalid_settings", "Invalid Codex approval policy", policy)
        config.execution.codex_approval_policy = policy
    for key, maximum in (
        ("codex_request_timeout_seconds", 300),
        ("codex_app_server_timeout_seconds", 86400),
    ):
        if key in patch:
            setattr(config.execution, key, _integer(patch[key], 1, maximum, key))
    for key in ("codex_model", "codex_provider", "codex_api_key_env", "codex_bin"):
        if key not in patch:
            continue
        value = str(patch[key]).strip()
        if key in {"codex_model", "codex_api_key_env", "codex_bin"} and not value:
            raise Problem("invalid_settings", "Codex setting cannot be empty", key)
        if key == "codex_api_key_env" and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", value
        ) is None:
            raise Problem("invalid_settings", "Invalid environment variable name", value)
        setattr(config.execution, key, value)


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise Problem("invalid_settings", "Expected an integer", field) from exc
    if not minimum <= parsed <= maximum:
        raise Problem("invalid_settings", "Value outside allowed range", field)
    return parsed


def _reject_unknown(patch: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(patch) - allowed
    if unknown:
        raise Problem("invalid_settings", "Unknown settings", ", ".join(sorted(unknown)))


def _file_revision(path: Path) -> str:
    return sha256(path.read_bytes() if path.exists() else b"").hexdigest()
