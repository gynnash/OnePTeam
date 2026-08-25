"""Global configuration loaded from ~/.onep/config.yaml and environment variables."""
from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

import yaml

# Load .env file if present — check cwd first, then package project root
_env_candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
for _ENV_PATH in _env_candidates:
    if _ENV_PATH.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_ENV_PATH)
        except ImportError:
            pass
        break


@dataclass
class LLMConfig:
    default_model: str = "deepseek/deepseek-chat"
    default_provider: str = "deepseek"
    complex_model: str = "openai/gpt-5.5"
    complex_provider: str = "openai"
    models: dict = field(default_factory=dict)
    pricing: dict = field(default_factory=lambda: {
        "deepseek/deepseek-chat":   {"input": 0.14, "output": 0.28},
        "deepseek/deepseek-v4-pro": {"input": 0.50, "output": 1.00},
        "openai/gpt-4o":            {"input": 2.50, "output": 10.00},
        "openai/gpt-4.1":           {"input": 2.00, "output": 8.00},
    })


@dataclass
class ProjectConfig:
    root_dir: str = "~/.onep"


@dataclass
class ExecutionConfig:
    """The only engineering backend: local Codex App Server over stdio."""

    codex_model: str = "gpt-5.6-terra"
    codex_provider: str = ""
    codex_auth_mode: str = "existing"
    codex_api_key_env: str = "OPENAI_API_KEY"
    codex_bin: str = "codex"
    codex_approval_policy: str = "on-request"
    codex_request_timeout_seconds: int = 30
    codex_app_server_timeout_seconds: int = 3600


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


def _default_config_yaml() -> str:
    """Generate the default config YAML from dataclass defaults."""
    return "# OnePTeam configuration\n" + yaml.dump(
        dataclasses.asdict(Config()), default_flow_style=False
    )


DEFAULT_CONFIG_YAML = _default_config_yaml()


def _config_dir() -> Path:
    return Path(os.path.expanduser("~/.onep"))


def _config_path() -> Path:
    return _config_dir() / "config.yaml"


def _ensure_config() -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = _config_path()
    if not config_file.exists():
        config_file.write_text(DEFAULT_CONFIG_YAML)


def load_config() -> Config:
    """Load config from ~/.onep/config.yaml, creating default if absent."""
    _ensure_config()
    raw = yaml.safe_load(_config_path().read_text()) or {}
    llm = LLMConfig(**(raw.get("llm") or {}))
    project = ProjectConfig(**(raw.get("project") or {}))
    execution_raw = raw.get("execution") or {}
    execution_fields = {value.name for value in dataclasses.fields(ExecutionConfig)}
    execution = ExecutionConfig(**{
        key: value for key, value in execution_raw.items()
        if key in execution_fields
    })
    return Config(
        llm=llm,
        project=project,
        execution=execution,
    )


def save_config(config: Config) -> None:
    """Save config back to disk."""
    _ensure_config()
    config_file = _config_path()
    raw = yaml.safe_load(config_file.read_text()) or {}
    raw.update({
        "llm": {
            "default_model": config.llm.default_model,
            "default_provider": config.llm.default_provider,
            "complex_model": config.llm.complex_model,
            "complex_provider": config.llm.complex_provider,
            "models": config.llm.models,
            "pricing": config.llm.pricing,
        },
        "project": {"root_dir": config.project.root_dir},
        "execution": dataclasses.asdict(config.execution),
    })
    _atomic_write(config_file, yaml.dump(raw, default_flow_style=False))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
