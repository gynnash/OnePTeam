"""LLM invocation via LiteLLM, abstracting provider differences."""
from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from typing import Any

from litellm import completion
from rich.console import Console

from onep.llm.router import resolve_model, get_api_key, get_api_base

console = Console()


class TokenUsage:
    """Token usage stats from the most recent LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        return self.total_tokens == 0

    def display(self) -> str:
        return (
            f"[dim]tokens: {self.prompt_tokens} in + {self.completion_tokens} out "
            f"= {self.total_tokens} total[/dim]"
        )


class LLMAdapter:
    """Unified interface for calling LLMs through LiteLLM."""

    def __init__(self):
        self.usage = TokenUsage()

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
        self._capture_usage(response)
        return response.choices[0].message.content

    def invoke_stream(self, system_prompt: str, user_prompt: str, stage_name: str) -> Iterator[str]:
        """Stream LLM response token by token. Usage captured from final chunk."""
        model_name, provider = resolve_model(stage_name)
        api_key = get_api_key(provider)
        api_base = get_api_base(provider)

        kwargs = {"model": model_name, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], "stream": True, "stream_options": {"include_usage": True}}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = completion(**kwargs)
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            self._capture_stream_usage(chunk)

    def invoke_with_tools_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        stage_name: str,
        max_tool_rounds: int = 8,
    ) -> Iterator[dict[str, Any]]:
        """Stream LLM response with tool calling support.

        Yields dicts with keys:
          type: "thinking" | "tool_call" | "token" | "done"
          content: str (for thinking/token), None otherwise
          tool_name: str (for tool_call only)
          tool_args: dict (for tool_call only)
          tool_result: str (for tool_call only)
          usage: TokenUsage (for done only)
        """
        model_name, provider = resolve_model(stage_name)
        api_key = get_api_key(provider)
        api_base = get_api_base(provider)

        tool_schemas = _tools_to_openai_schema(tools)
        tool_map = {t.name: t for t in tools}

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        rounds = 0
        while rounds < max_tool_rounds:
            rounds += 1
            kwargs: dict = {
                "model": model_name,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tool_schemas:
                kwargs["tools"] = tool_schemas
                kwargs["tool_choice"] = "auto"
            if api_key:
                kwargs["api_key"] = api_key
            if api_base:
                kwargs["api_base"] = api_base

            response = completion(**kwargs)

            # accumulate streaming response
            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}  # index -> {id, name, args_str}

            for chunk in response:
                delta = chunk.choices[0].delta
                self._capture_stream_usage(chunk)

                # text content
                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "token", "content": delta.content}

                # tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "args_str": "",
                            }
                        acc = tool_calls_acc[idx]
                        if tc.id:
                            acc["id"] = tc.id
                        if tc.function and tc.function.name:
                            acc["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            acc["args_str"] += tc.function.arguments

            # process completed tool calls
            if tool_calls_acc:
                # add assistant message with tool calls
                # OpenAI API spec: omit 'content' when only tool_calls (no text)
                # DeepSeek rejects content=None or content=""
                assistant_msg: dict = {"role": "assistant"}
                text_content = "".join(content_parts).strip()
                if text_content:
                    assistant_msg["content"] = text_content
                tc_list = []
                tool_results: list[dict] = []  # collect, append after assistant
                for idx in sorted(tool_calls_acc.keys()):
                    tc_data = tool_calls_acc[idx]
                    try:
                        args = json.loads(tc_data["args_str"])
                    except json.JSONDecodeError:
                        args = {}
                    tc_list.append({
                        "id": tc_data["id"],
                        "type": "function",
                        "function": {"name": tc_data["name"], "arguments": json.dumps(args, ensure_ascii=False)},
                    })

                    # execute tool
                    tool = tool_map.get(tc_data["name"])
                    if tool:
                        yield {
                            "type": "tool_call",
                            "tool_name": tc_data["name"],
                            "tool_args": args,
                        }
                        try:
                            result = tool.run(**args)
                        except Exception as e:
                            result = f"Error: {e}"
                        if len(result) > 4000:
                            result = result[:4000] + "\n... (truncated)"
                        yield {
                            "type": "tool_call_result",
                            "tool_name": tc_data["name"],
                            "tool_result": result,
                        }
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc_data["id"],
                            "content": str(result),
                        })
                    else:
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc_data["id"],
                            "content": f"Error: unknown tool '{tc_data['name']}'",
                        })

                if tc_list:
                    assistant_msg["tool_calls"] = tc_list
                messages.append(assistant_msg)
                messages.extend(tool_results)
            else:
                # no tool calls — model is done
                yield {"type": "done", "usage": self.usage}
                return

        # max rounds reached
        yield {"type": "done", "usage": self.usage}

    def _capture_usage(self, response: Any) -> None:
        if hasattr(response, "usage") and response.usage:
            self.usage.prompt_tokens = response.usage.prompt_tokens or 0
            self.usage.completion_tokens = response.usage.completion_tokens or 0
            self.usage.total_tokens = response.usage.total_tokens or 0

    def _capture_stream_usage(self, chunk: Any) -> None:
        if hasattr(chunk, "usage") and chunk.usage:
            self.usage.prompt_tokens = chunk.usage.prompt_tokens or 0
            self.usage.completion_tokens = chunk.usage.completion_tokens or 0
            self.usage.total_tokens = chunk.usage.total_tokens or 0

    def reset_usage(self) -> None:
        self.usage = TokenUsage()


def _tools_to_openai_schema(tools: list) -> list[dict]:
    """Convert CrewAI tool objects to OpenAI-compatible tool schemas."""
    schemas = []
    for tool in tools:
        params_schema = _build_params_schema(tool)
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": params_schema,
            },
        })
    return schemas


def _build_params_schema(tool) -> dict:
    """Build a JSON Schema for a tool's _run parameters using inspect."""
    try:
        sig = inspect.signature(tool._run)
    except (ValueError, TypeError):
        return {"type": "object", "properties": {}}

    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
        py_type = str if param.annotation is inspect.Parameter.empty else param.annotation
        json_type = type_map.get(py_type, "string")
        prop = {"type": json_type}
        if param.default is not inspect.Parameter.empty and param.default is not None:
            prop["default"] = param.default
        else:
            required.append(name)
        properties[name] = prop

    return {"type": "object", "properties": properties, "required": required}


_adapter: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LLMAdapter()
    return _adapter


def display_usage() -> None:
    """Print token usage from the last LLM call, if available."""
    llm = get_llm()
    if not llm.usage.is_empty:
        console.print(llm.usage.display())
