"""Route tasks to the appropriate LLM model based on complexity."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum

from onep.config import load_config


class TaskComplexity(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    COMPLEX = "complex"


COMPLEX_STAGES = {
    "pm", "designer", "architect", "strategy_architect",
    "optimize_developer", "greenfield_engineer", "code_reviewer",
    "harness_researcher", "harness_architect", "harness_distiller",
    "harness_cross_distiller",
    "harness_article_extract", "harness_article_cluster",
    "harness_article_graph", "harness_article_insight",
    "harness_article_narrative",
}

_MODEL_OVERRIDES: ContextVar[dict[str, str]] = ContextVar(
    "onep_model_overrides", default={}
)


def resolve_model(stage_name: str, task_complexity: TaskComplexity = TaskComplexity.STANDARD) -> tuple[str, str]:
    """Return (model_name, provider) for a given stage and complexity."""
    config = load_config()
    llm = config.llm
    overrides = _MODEL_OVERRIDES.get()

    if task_complexity == TaskComplexity.COMPLEX or stage_name in COMPLEX_STAGES:
        return (
            overrides.get("complex_model") or llm.complex_model,
            overrides.get("complex_provider") or llm.complex_provider,
        )

    return (
        overrides.get("default_model") or llm.default_model,
        overrides.get("default_provider") or llm.default_provider,
    )


@contextmanager
def model_overrides(options):
    values = {
        key: str(getattr(options, key, "") or "")
        for key in (
            "default_model",
            "default_provider",
            "complex_model",
            "complex_provider",
        )
    }
    token = _MODEL_OVERRIDES.set(values)
    try:
        yield
    finally:
        _MODEL_OVERRIDES.reset(token)


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
