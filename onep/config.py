"""Global configuration loaded from ~/.onep/config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

import yaml


DEFAULT_CONFIG_YAML = """\
# OnePTeam configuration
llm:
  default_model: deepseek/deepseek-chat
  default_provider: deepseek
  complex_model: openai/gpt-5.5
  complex_provider: openai
  models:
    deepseek:
      api_key: ""
      api_base: https://api.deepseek.com/v1
    openai:
      api_key: ""
      api_base: https://api.openai.com/v1

project:
  root_dir: ~/.onep

pipeline:
  auto_approve: false
  max_retries: 3
  test_timeout: 300
"""


@dataclass
class LLMConfig:
    default_model: str = "deepseek/deepseek-chat"
    default_provider: str = "deepseek"
    complex_model: str = "openai/gpt-5.5"
    complex_provider: str = "openai"
    models: dict = field(default_factory=dict)


@dataclass
class ProjectConfig:
    root_dir: str = "~/.onep"


@dataclass
class PipelineConfig:
    auto_approve: bool = False
    max_retries: int = 3
    test_timeout: int = 300


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


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

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        default_model=llm_raw.get("default_model", "deepseek/deepseek-chat"),
        default_provider=llm_raw.get("default_provider", "deepseek"),
        complex_model=llm_raw.get("complex_model", "openai/gpt-5.5"),
        complex_provider=llm_raw.get("complex_provider", "openai"),
        models=llm_raw.get("models", {}),
    )

    project_raw = raw.get("project", {})
    project = ProjectConfig(root_dir=project_raw.get("root_dir", "~/.onep"))

    pipeline_raw = raw.get("pipeline", {})
    pipeline = PipelineConfig(
        auto_approve=pipeline_raw.get("auto_approve", False),
        max_retries=pipeline_raw.get("max_retries", 3),
        test_timeout=pipeline_raw.get("test_timeout", 300),
    )

    return Config(llm=llm, project=project, pipeline=pipeline)


def save_config(config: Config) -> None:
    """Save config back to disk."""
    _ensure_config()
    raw = {
        "llm": {
            "default_model": config.llm.default_model,
            "default_provider": config.llm.default_provider,
            "complex_model": config.llm.complex_model,
            "complex_provider": config.llm.complex_provider,
            "models": config.llm.models,
        },
        "project": {"root_dir": config.project.root_dir},
        "pipeline": {
            "auto_approve": config.pipeline.auto_approve,
            "max_retries": config.pipeline.max_retries,
            "test_timeout": config.pipeline.test_timeout,
        },
    }
    _config_path().write_text(yaml.dump(raw, default_flow_style=False))
