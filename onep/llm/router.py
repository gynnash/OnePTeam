"""Route tasks to the appropriate LLM model based on complexity."""
from __future__ import annotations

import os
from enum import Enum

from onep.config import load_config


class TaskComplexity(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    COMPLEX = "complex"


COMPLEX_STAGES = {"pm", "designer", "architect", "analyzer"}


def resolve_model(stage_name: str, task_complexity: TaskComplexity = TaskComplexity.STANDARD) -> tuple[str, str]:
    """Return (model_name, provider) for a given stage and complexity."""
    config = load_config()
    llm = config.llm

    if task_complexity == TaskComplexity.COMPLEX or stage_name in COMPLEX_STAGES:
        return llm.complex_model, llm.complex_provider

    return llm.default_model, llm.default_provider


def get_api_key(provider: str) -> str:
    """Get API key for provider. Priority: env var > config file."""
    env_key = f"{provider.upper()}_API_KEY"
    if os.environ.get(env_key):
        return os.environ[env_key]

    config = load_config()
    provider_cfg = config.llm.models.get(provider, {})
    return provider_cfg.get("api_key", "") or ""


def get_api_base(provider: str) -> str:
    """Get API base URL for provider. Priority: env var > config file."""
    env_key = f"{provider.upper()}_API_BASE"
    if os.environ.get(env_key):
        return os.environ[env_key]

    config = load_config()
    provider_cfg = config.llm.models.get(provider, {})
    return provider_cfg.get("api_base", "") or ""
