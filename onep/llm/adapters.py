"""LLM invocation via LiteLLM, abstracting provider differences."""
from __future__ import annotations

import inspect
import json
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any

from litellm import completion
from rich.console import Console

from onep.llm.router import resolve_model, get_api_key, get_api_base
from onep.llm.trajectory import StuckDetector, TrajectoryRecorder, TrajectorySink

console = Console()


@dataclass(frozen=True)
class TokenUsage:
    """Token usage stats from the most recent LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_id: str = field(default_factory=lambda: uuid4().hex)

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

    @property
    def last_usage(self) -> TokenUsage:
        return self.usage

    def invoke(self, system_prompt: str, user_prompt: str, stage_name: str) -> str:
        self.reset_usage()
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
        self.reset_usage()
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
        trajectory_sink: TrajectorySink | None = None,
        stuck_detector: StuckDetector | None = None,
        mutation_nudge_round: int = 0,
        block_full_test_commands: bool = False,
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
        self.reset_usage()
        trajectory = TrajectoryRecorder(trajectory_sink)
        detector = stuck_detector or StuckDetector()
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
        mutated = False
        mutation_nudged = False
        while rounds < max_tool_rounds:
            rounds += 1
            trajectory.emit("model_round_started", round=rounds)
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
                self._capture_stream_usage(chunk, accumulate=True)

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
                    trajectory.emit(
                        "model_message", round=rounds, content=text_content
                    )
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
                        stuck_reason = detector.observe_call(
                            tc_data["name"], args
                        )
                        trajectory.emit(
                            "tool_requested",
                            round=rounds,
                            tool_name=tc_data["name"],
                            tool_args=args,
                        )
                        if stuck_reason:
                            trajectory.emit("loop_stuck", reason=stuck_reason)
                            yield {"type": "stuck", "reason": stuck_reason}
                            yield {
                                "type": "done",
                                "usage": self.usage,
                                "termination_reason": "stuck",
                            }
                            return
                        yield {
                            "type": "tool_call",
                            "tool_name": tc_data["name"],
                            "tool_args": args,
                        }
                        if (
                            block_full_test_commands
                            and tc_data["name"] == "shell"
                            and _is_broad_pytest_command(
                                str(args.get("command") or "")
                            )
                        ):
                            result = (
                                "Blocked: full-suite pytest is owned by the external "
                                "quality gate. Implement the current slice and run only "
                                "its focused tests."
                            )
                            trajectory.emit(
                                "full_test_blocked", round=rounds,
                                command=str(args.get("command") or ""),
                            )
                        else:
                            try:
                                result = tool.run(**args)
                            except Exception as e:
                                result = f"Error: {e}"
                        if (
                            tc_data["name"] in {"file_write", "edit"}
                            and not str(result).startswith("Error:")
                        ):
                            mutated = True
                        if len(result) > 4000:
                            result = result[:4000] + "\n... (truncated)"
                        trajectory.emit(
                            "tool_completed",
                            round=rounds,
                            tool_name=tc_data["name"],
                            tool_result=result,
                        )
                        yield {
                            "type": "tool_call_result",
                            "tool_name": tc_data["name"],
                            "tool_result": result,
                        }
                        stuck_reason = detector.observe_result(
                            tc_data["name"], str(result)
                        )
                        if stuck_reason:
                            trajectory.emit("loop_stuck", reason=stuck_reason)
                            yield {"type": "stuck", "reason": stuck_reason}
                            yield {
                                "type": "done",
                                "usage": self.usage,
                                "termination_reason": "stuck",
                            }
                            return
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
                if (
                    mutation_nudge_round > 0
                    and rounds >= mutation_nudge_round
                    and not mutated
                    and not mutation_nudged
                ):
                    mutation_nudged = True
                    trajectory.emit("implementation_nudge", round=rounds)
                    messages.append({
                        "role": "user",
                        "content": (
                            "Implementation checkpoint: no file has been changed yet. "
                            "Stop broad repository analysis now. In the next response, "
                            "batch-create or edit all production and test files required "
                            "by the current slice. Do not run the full test suite."
                        ),
                    })
            else:
                # no tool calls — model is done
                text_content = "".join(content_parts).strip()
                if text_content:
                    trajectory.emit(
                        "model_message", round=rounds, content=text_content
                    )
                trajectory.emit("loop_completed", rounds=rounds)
                yield {
                    "type": "done",
                    "usage": self.usage,
                    "termination_reason": "completed",
                }
                return

            # one round before limit: nudge model to produce output
            if rounds == max_tool_rounds - 1:
                messages.append({
                    "role": "user",
                    "content": "请基于已读取的文件，立即输出最终分析结果。不要再调用工具。",
                })

        # max rounds reached — ask for final output
        if rounds >= max_tool_rounds:
            trajectory.emit("loop_limit_reached", rounds=rounds)
            yield {"type": "limit_reached", "rounds": rounds}
            yield {
                "type": "done",
                "usage": self.usage,
                "termination_reason": "tool_round_limit",
            }
            return

    def _capture_usage(self, response: Any) -> None:
        if hasattr(response, "usage") and response.usage:
            self.usage = TokenUsage(
                response.usage.prompt_tokens or 0,
                response.usage.completion_tokens or 0,
                response.usage.total_tokens or 0,
                self.usage.call_id,
            )

    def _capture_stream_usage(self, chunk: Any, accumulate: bool = False) -> None:
        if hasattr(chunk, "usage") and chunk.usage:
            prompt = chunk.usage.prompt_tokens or 0
            completion = chunk.usage.completion_tokens or 0
            total = chunk.usage.total_tokens or 0
            if accumulate:
                prompt += self.usage.prompt_tokens
                completion += self.usage.completion_tokens
                total += self.usage.total_tokens
            self.usage = TokenUsage(
                prompt, completion, total, self.usage.call_id
            )

    def reset_usage(self) -> None:
        self.usage = TokenUsage()


def _is_broad_pytest_command(command: str) -> bool:
    """Detect pytest invocations that target the whole repository or test tree."""
    normalized = command.replace("&&", "|").replace(";", "|")
    for segment in normalized.split("|"):
        try:
            parts = shlex.split(segment.strip())
        except ValueError:
            continue
        if "pytest" not in parts:
            continue
        index = parts.index("pytest")
        targets = [
            value for value in parts[index + 1:]
            if not value.startswith("-")
            and not _is_shell_redirection(value)
        ]
        if not targets or all(
            value.rstrip("/") in {".", "test", "tests"}
            for value in targets
        ):
            return True
    return False


def _is_shell_redirection(value: str) -> bool:
    compact = value.replace(" ", "")
    if compact in {">", ">>", "/dev/null"}:
        return True
    return any(marker in compact for marker in (">&", "2>", "1>", "<"))


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
