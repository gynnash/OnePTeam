"""Validated settings capabilities shared by the CLI and Web surfaces."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from onep.config import load_config, save_config, _config_path
from onep.domain import Problem
from onep.greenfield.gates import discover_quality_commands, validate_gate_commands
from onep.greenfield.models import GreenfieldOptions
from onep.harness.persistence import load_harness_run
from onep.persistence.state import load_state, save_state


def global_settings_read(_payload, _context) -> dict[str, Any]:
    config = load_config()
    return {
        "settings": _redacted_global(config),
        "revision": _file_revision(_config_path()),
        "applies_to": "next_job",
    }


def global_settings_update(store):
    def update(payload, _context) -> dict[str, Any]:
        if store.has_active_jobs():
            raise Problem(
                "settings_locked_by_active_jobs",
                "Settings are locked",
                "Wait for queued or running jobs to finish before changing global settings.",
                actionable=True,
            )
        revision = str(payload.get("revision") or "")
        if revision and revision != _file_revision(_config_path()):
            raise Problem(
                "settings_revision_conflict",
                "Settings changed elsewhere",
                "Reload settings before saving your changes.",
                actionable=True,
            )
        patch = dict(payload.get("patch") or {})
        unknown = set(patch) - {"llm", "pipeline", "run_defaults"}
        if unknown:
            raise Problem("invalid_settings", "Unknown settings", ", ".join(sorted(unknown)))
        config = load_config()
        _update_llm(config, dict(patch.get("llm") or {}))
        _update_pipeline(config, dict(patch.get("pipeline") or {}))
        _update_run_defaults(config, dict(patch.get("run_defaults") or {}))
        save_config(config)
        return global_settings_read({}, _context)

    return update


def project_settings_read(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path)
    state = load_state(workspace)
    saved = dict(state.artifacts.get("greenfield_options") or {})
    defaults = GreenfieldOptions.configured(saved)
    run = load_harness_run(workspace)
    active_options = None
    if run and run.greenfield_run:
        active_options = run.greenfield_run.options.to_dict()
    config = load_config()
    effective = defaults.to_dict()
    for kind in ("default", "complex"):
        effective[f"{kind}_model"] = (
            effective.get(f"{kind}_model") or getattr(config.llm, f"{kind}_model")
        )
        effective[f"{kind}_provider"] = (
            effective.get(f"{kind}_provider") or getattr(config.llm, f"{kind}_provider")
        )
    return {
        "project_id": project.id,
        "defaults": defaults.to_dict(),
        "effective": effective,
        "active_run": active_options,
        "is_running": bool(run and run.status == "running"),
        "revision": _settings_revision(saved),
        "applies_to": "next_invocation",
    }


def project_settings_update(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path)
    state = load_state(workspace)
    saved = dict(state.artifacts.get("greenfield_options") or {})
    revision = str(payload.get("revision") or "")
    if revision and revision != _settings_revision(saved):
        raise Problem(
            "settings_revision_conflict",
            "Project settings changed elsewhere",
            "Reload project settings before saving.",
            actionable=True,
        )
    patch = dict(payload.get("patch") or {})
    allowed = {
        "max_rounds", "max_repairs_per_slice", "max_cost", "test_commands",
        "deploy_mode", "non_interactive", "verbose", "default_model",
        "default_provider", "complex_model", "complex_provider",
    }
    unknown = set(patch) - allowed
    if unknown:
        raise Problem("invalid_settings", "Unknown project settings", ", ".join(sorted(unknown)))
    merged = GreenfieldOptions.configured(saved).to_dict()
    merged.update(patch)
    normalized = _strict_project_options(merged)
    state.artifacts["greenfield_options"] = normalized
    state.artifacts["greenfield_options_schema"] = 2
    save_state(workspace, state)
    return project_settings_read({"project": project.id}, context)


def project_test_commands_discover(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    commands = discover_quality_commands(Path(project.workspace_path))
    validate_gate_commands(commands)
    return {"commands": commands, "executed": False}


def model_connection_test(payload, context) -> dict[str, Any]:
    from onep.llm.adapters import LLMAdapter
    from onep.llm.router import model_overrides

    project_options = GreenfieldOptions()
    project_ref = str(payload.get("project") or context.project_id or "")
    if project_ref:
        settings = project_settings_read({"project": project_ref}, context)
        project_options = GreenfieldOptions.from_dict(settings["defaults"])
    kind = str(payload.get("kind") or "default")
    stage = "architect" if kind == "complex" else "settings_connection_test"
    with model_overrides(project_options):
        response = LLMAdapter().invoke(
            system_prompt="You are a connection check. Reply with OK only.",
            user_prompt="OK",
            stage_name=stage,
        )
    return {"connected": True, "response": str(response)[:80], "kind": kind}


def _project(payload, context):
    from onep.application.defaults import resolve_project

    return resolve_project(str(payload.get("project") or context.project_id))


def _redacted_global(config) -> dict[str, Any]:
    providers = {config.llm.default_provider, config.llm.complex_provider}
    providers.update(config.llm.models)
    configured = {}
    for provider in sorted(value for value in providers if value):
        environment = bool(os.environ.get(f"{provider.upper()}_API_KEY"))
        config_value = bool((config.llm.models.get(provider) or {}).get("api_key"))
        configured[provider] = {
            "configured": environment or config_value,
            "source": "environment" if environment else "config" if config_value else "missing",
        }
    return {
        "llm": {
            "default_model": config.llm.default_model,
            "default_provider": config.llm.default_provider,
            "complex_model": config.llm.complex_model,
            "complex_provider": config.llm.complex_provider,
            "providers": configured,
        },
        "pipeline": {
            "test_timeout": config.pipeline.test_timeout,
            "stage_output_tokens": dict(config.pipeline.stage_output_tokens),
        },
        "run_defaults": asdict(config.run_defaults),
    }


def _update_llm(config, patch: dict[str, Any]) -> None:
    allowed = {"default_model", "default_provider", "complex_model", "complex_provider"}
    _reject_unknown(patch, allowed)
    for key, value in patch.items():
        text = str(value).strip()
        if not text:
            raise Problem("invalid_settings", "Model setting cannot be empty", key)
        setattr(config.llm, key, text)


def _update_pipeline(config, patch: dict[str, Any]) -> None:
    allowed = {"test_timeout", "stage_output_tokens"}
    _reject_unknown(patch, allowed)
    if "test_timeout" in patch:
        config.pipeline.test_timeout = _integer(patch["test_timeout"], 1, 7200, "test_timeout")
    if "stage_output_tokens" in patch:
        values = dict(patch["stage_output_tokens"] or {})
        allowed_stages = set(config.pipeline.stage_output_tokens)
        _reject_unknown(values, allowed_stages)
        config.pipeline.stage_output_tokens.update({
            key: _integer(value, 256, 131072, key) for key, value in values.items()
        })


def _update_run_defaults(config, patch: dict[str, Any]) -> None:
    allowed = set(asdict(config.run_defaults))
    _reject_unknown(patch, allowed)
    if "max_rounds" in patch:
        config.run_defaults.max_rounds = _integer(patch["max_rounds"], 1, 1000, "max_rounds")
    if "max_repairs_per_slice" in patch:
        config.run_defaults.max_repairs_per_slice = _integer(
            patch["max_repairs_per_slice"], 1, 100, "max_repairs_per_slice"
        )
    if "max_cost" in patch:
        config.run_defaults.max_cost = _number(patch["max_cost"], 0, 1_000_000, "max_cost")
    if "deploy_mode" in patch:
        mode = str(patch["deploy_mode"])
        if mode not in {"verify", "local", "none"}:
            raise Problem("invalid_settings", "Invalid deploy mode", mode)
        config.run_defaults.deploy_mode = mode
    for key in ("non_interactive", "verbose"):
        if key in patch:
            setattr(config.run_defaults, key, bool(patch[key]))


def _strict_project_options(raw: dict[str, Any]) -> dict[str, Any]:
    commands = [str(value).strip() for value in raw.get("test_commands") or [] if str(value).strip()]
    commands = list(dict.fromkeys(commands))
    if len(commands) > 20 or any(len(command) > 1000 for command in commands):
        raise Problem("invalid_settings", "Too many or oversized test commands")
    try:
        validate_gate_commands(commands)
    except ValueError as exc:
        raise Problem("invalid_test_command", "Unsafe or unsupported test command", str(exc)) from exc
    deploy_mode = str(raw.get("deploy_mode") or "verify")
    if deploy_mode not in {"verify", "local", "none"}:
        raise Problem("invalid_settings", "Invalid deploy mode", deploy_mode)
    return GreenfieldOptions(
        max_rounds=_integer(raw.get("max_rounds", 100), 1, 1000, "max_rounds"),
        max_repairs_per_slice=_integer(
            raw.get("max_repairs_per_slice", 8), 1, 100, "max_repairs_per_slice"
        ),
        max_cost=_number(raw.get("max_cost", 0), 0, 1_000_000, "max_cost"),
        test_commands=commands,
        deploy_mode=deploy_mode,
        non_interactive=bool(raw.get("non_interactive", False)),
        verbose=bool(raw.get("verbose", False)),
        default_model=str(raw.get("default_model") or "").strip(),
        default_provider=str(raw.get("default_provider") or "").strip(),
        complex_model=str(raw.get("complex_model") or "").strip(),
        complex_provider=str(raw.get("complex_provider") or "").strip(),
    ).to_dict()


def _integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise Problem("invalid_settings", "Expected an integer", field) from exc
    if not minimum <= parsed <= maximum:
        raise Problem("invalid_settings", "Value outside allowed range", field)
    return parsed


def _number(value: Any, minimum: float, maximum: float, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise Problem("invalid_settings", "Expected a number", field) from exc
    if not minimum <= parsed <= maximum:
        raise Problem("invalid_settings", "Value outside allowed range", field)
    return parsed


def _reject_unknown(patch: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(patch) - allowed
    if unknown:
        raise Problem("invalid_settings", "Unknown settings", ", ".join(sorted(unknown)))


def _file_revision(path: Path) -> str:
    return sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def _settings_revision(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return sha256(encoded).hexdigest()
