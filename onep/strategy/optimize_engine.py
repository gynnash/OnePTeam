"""Optimize Engine — open agent loop for strategy item execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from onep.strategy.models import StrategyItem
from onep.strategy.project_context import load_project_context

console = Console()

EXECUTE_PROMPT = """你是一位全栈研发工程师。请根据以下优化 Plan，独立完成代码实现和验证。

## 优化方向

- 标题: {title}
- 文件位置: {file_location}
- 问题摘要: {summary}
- 策略标签: {tags}
- 影响级别: {impact}

## Plan 内容

{plan_content}

## 源码位置

{source_path}

## 工作流程

请按以下步骤自主完成工作，遇到问题自行排查修复：

1. **理解上下文**：用 grep 搜索相关代码，用 file_read 读取关键文件，理解现有实现
2. **实现改动**：用 file_write 修改源码，每次修改聚焦一个文件
3. **验证**：用 lint 检查代码质量，用 shell 运行测试
4. **修复**：如果测试失败，分析失败原因，修改代码，重新测试，直到通过
5. **报告**：完成后总结改动了哪些文件，测试结果如何

要求：
- 只修改必要的代码，不引入无关变更
- 保持现有代码风格一致
- 测试失败时必须修复，不要跳过"""


class OptimizeEngine:
    """Open-loop execution engine for strategy optimization items."""

    def execute(self, item: StrategyItem, source_path: str, workspace: str,
                llm_adapter=None) -> dict:
        """Execute a strategy item in an open agent loop.

        The agent reads the Plan, understands the codebase, makes changes,
        runs tests, fixes failures, and reports results — all in one call.

        Returns {success, files_changed, steps, test_output}.
        """
        result = {"success": False, "files_changed": [], "steps": []}

        if llm_adapter is None:
            result["error"] = "LLM not available"
            result["steps"].append({"name": "execute", "output": "LLM not available"})
            return result

        plan_content = ""
        if item.plan_path:
            p = Path(item.plan_path)
            if p.exists():
                plan_content = p.read_text()[:4000]

        prompt = EXECUTE_PROMPT.format(
            title=item.title,
            file_location=item.file_location,
            summary=item.summary,
            tags=", ".join(item.tags) if item.tags else "",
            impact=item.impact,
            plan_content=plan_content or item.summary,
            source_path=source_path,
        )

        ctx = load_project_context(Path(workspace), source_path)
        if ctx:
            prompt = prompt + f"\n\n## 项目上下文\n\n{ctx[:2000]}"

        output = _invoke_stream(llm_adapter, "developer", prompt, source_path)
        result["steps"].append({"name": "execute", "output": output})

        if not output:
            result["error"] = "agent produced no output"
            return result

        result["files_changed"] = _extract_files(output)
        result["test_output"] = {
            "passed": False,
            "output": "External test gate has not run.",
        }
        result["error"] = "external test gate required"

        return result

    def execute_attempt(
        self,
        item: StrategyItem,
        source_path: str,
        workspace: str,
        llm_adapter,
        feedback: str = "",
        memory_context: str = "",
    ) -> "EngineAttemptResult":
        if llm_adapter is None:
            raise RuntimeError("LLM not available")
        plan_content = item.summary
        if item.plan_path and Path(item.plan_path).exists():
            plan_content = Path(item.plan_path).read_text()[:12000]
        prompt = EXECUTE_PROMPT.format(
            title=item.title,
            file_location=item.file_location,
            summary=item.summary,
            tags=", ".join(item.tags),
            impact=item.impact,
            plan_content=plan_content,
            source_path=source_path,
        )
        if feedback:
            prompt += (
                "\n\n## 上一轮门禁反馈\n"
                f"{feedback}\n请在当前分支继续修复，不要回滚已正确的改动。"
            )
        if memory_context:
            from onep.memory.context import append_memory_context
            prompt = append_memory_context(prompt, memory_context)
        ctx = load_project_context(Path(workspace), source_path)
        if ctx:
            prompt += f"\n\n## 项目上下文\n\n{ctx[:4000]}"
        output = _invoke_stream(
            llm_adapter, "developer", prompt, source_path,
            model_stage="optimize_developer",
        )
        return EngineAttemptResult(output=output or "")


def _invoke_stream(llm_adapter, agent_name: str, prompt: str,
                   source_path: str, model_stage: str | None = None) -> str:
    """Invoke agent with tools and streaming output."""
    from onep.agents.registry import get_agent
    from onep.llm.router import resolve_model

    agent = get_agent(agent_name, workspace=source_path, source_id="")
    system_prompt = (
        f"{agent.role}\n\n"
        f"目标: {agent.goal}\n\n"
        f"背景: {agent.backstory}\n\n"
        f"你可以使用 grep 搜索代码，用 file_read 读取文件，用 file_write 修改代码，"
        f"用 shell 运行命令，用 lint 检查代码质量。"
        f"遇到错误要自己排查修复，不要放弃。"
    )
    tools = getattr(agent, "tools", []) or []
    stage_name = model_stage or agent_name
    model_name, _ = resolve_model(stage_name)

    console.print(f"  [dim]Agent: {agent.role} | Model: {model_name}[/dim]")
    tool_names = [t.name for t in tools]
    console.print(f"  [dim]Tools: {', '.join(tool_names)}[/dim]")

    parts = []
    for event in llm_adapter.invoke_with_tools_stream(
        system_prompt=system_prompt,
        user_prompt=prompt,
        tools=tools,
        stage_name=stage_name,
        max_tool_rounds=15,
    ):
        if event["type"] == "tool_call":
            args_str = ", ".join(
                f"{k}={_brief_val(v)}"
                for k, v in event.get("tool_args", {}).items()
            )
            console.print(f"  [dim]{event['tool_name']}({args_str})[/dim]")
        elif event["type"] == "token":
            console.print(event["content"], end="")
            parts.append(event["content"])
        elif event["type"] == "done":
            pass

    console.print()
    from onep.llm.adapters import display_usage
    display_usage()
    return "".join(parts)


def _brief_val(v) -> str:
    s = str(v)
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    if len(s) > 70:
        return s[:67] + "..."
    return s


def _extract_files(output: str) -> list[str]:
    import re
    files = set()
    for m in re.finditer(
        r'(?:file_write|modified|changed|written|修改)[^\n]*?([\w./-]+\.\w+)',
        output,
    ):
        files.add(m.group(1))
    return sorted(files)[:20]


@dataclass(frozen=True)
class EngineAttemptResult:
    output: str
