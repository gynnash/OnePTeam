"""LLM invocation via LiteLLM, abstracting provider differences."""
from __future__ import annotations

from litellm import completion

from onep.llm.router import resolve_model, get_api_key, get_api_base


class LLMAdapter:
    """Unified interface for calling LLMs through LiteLLM."""

    def invoke(self, system_prompt: str, user_prompt: str, stage_name: str) -> str:
        model_name, provider = resolve_model(stage_name)
        api_key = get_api_key(provider)
        api_base = get_api_base(provider)

        kwargs = {"model": model_name, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = completion(**kwargs)
        return response.choices[0].message.content


_adapter: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LLMAdapter()
    return _adapter
