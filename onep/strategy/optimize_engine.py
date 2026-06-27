"""Optimize Engine -- shared 3-step execution for strategy items."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from onep.strategy.models import StrategyItem

console = Console()

ARCHITECT_REFINE_PROMPT = """基于以下优化Plan，输出一份技术实现方案。

优化方向: {title}
问题摘要: {summary}
策略标签: {tags}
影响级别: {impact}
文件位置: {file_location}

Plan 内容:
{plan_content}

输出一份简洁的技术实现方案，包含:
1. 需要修改的文件列表
2. 每个文件的修改要点
3. API 变更（如有）
4. 实现风险"""

DEVELOPER_PROMPT = """根据技术方案实现代码改动。

技术方案:
{tech_plan}

源代码位置: {source_path}

请直接修改源码文件。使用 file_write 写入改动，使用 shell 运行 lint 检查。
每个文件改动后确保代码可运行。"""

TESTER_PROMPT = """验证代码改动。

源代码位置: {source_path}
改动文件: {files_changed}

请运行相关测试。如果有 pytest 配置，运行 pytest。
输出测试结果: passed/failed, 测试数量, 失败详情。"""


class OptimizeEngine:
    """3-step execution engine for strategy optimization items."""

    def execute(self, item: StrategyItem, source_path: str, workspace: str,
                llm_adapter=None) -> dict:
        """Execute architect_refine, developer_implement, tester_verify.
        Returns {success, files_changed, steps, test_output}.
        """
        result = {"success": False, "files_changed": [], "steps": []}

        # Step 1: Architect refine
        console.print("\n  [bold cyan]--- Step 1/3: ---[/bold cyan]")
        tech_plan = self._step_architect(item, source_path, llm_adapter)
        result["steps"].append({"name": "architect_refine", "output": tech_plan})

        if not tech_plan:
            result["error"] = "architect_refine produced no output"
            return result

        # Step 2: Developer implement
        console.print("\n  [bold cyan]--- Step 2/3: ---[/bold cyan]")
        impl_result = self._step_developer(tech_plan, source_path, llm_adapter)
        result["steps"].append({"name": "developer_implement", "output": impl_result})

        if not impl_result:
            result["error"] = "developer_implement produced no output"
            return result

        result["files_changed"] = impl_result.get("files", [])

        # Step 3: Tester verify
        console.print("\n  [bold cyan]--- Step 3/3: ---[/bold cyan]")
        test_result = self._step_tester(source_path, result["files_changed"], llm_adapter)
        result["steps"].append({"name": "tester_verify", "output": test_result})
        result["test_output"] = test_result
        result["success"] = test_result.get("passed", False) if test_result else False

        return result

    def _step_architect(self, item, source_path, llm_adapter):
        if llm_adapter is None:
            return "LLM not available -- cannot execute without API key"
        plan_content = ""
        if item.plan_path:
            p = Path(item.plan_path)
            if p.exists():
                plan_content = p.read_text()[:3000]
        prompt = ARCHITECT_REFINE_PROMPT.format(
            title=item.title, summary=item.summary,
            tags=", ".join(item.tags), impact=item.impact,
            file_location=item.file_location,
            plan_content=plan_content or item.summary,
        )
        return _invoke_stream(llm_adapter, "architect", prompt, source_path)

    def _step_developer(self, tech_plan, source_path, llm_adapter):
        if llm_adapter is None:
            return {"output": "LLM not available", "files": []}
        prompt = DEVELOPER_PROMPT.format(
            tech_plan=tech_plan, source_path=source_path,
        )
        output = _invoke_stream(llm_adapter, "developer", prompt, source_path)
        return {"output": output, "files": _extract_files(output)}

    def _step_tester(self, source_path, files_changed, llm_adapter):
        if llm_adapter is None:
            return {"passed": False, "output": "LLM not available"}
        prompt = TESTER_PROMPT.format(
            source_path=source_path,
            files_changed=", ".join(files_changed) if files_changed else "unknown",
        )
        output = _invoke_stream(llm_adapter, "tester", prompt, source_path)
        passed = "passed" in output.lower() and "failed" not in output.lower()
        return {"passed": passed, "output": output}


def _invoke_stream(llm_adapter, agent_name: str, prompt: str,
                   source_path: str) -> str:
    """Invoke agent with tools and streaming output."""
    from onep.agents.registry import get_agent
    from onep.llm.router import resolve_model

    agent = get_agent(agent_name, workspace=source_path, source_id="")
    system_prompt = (
        f"{agent.role}\n\n"
        f": {agent.goal}\n\n"
        f": {agent.backstory}\n\n"
        f""
    )
    tools = getattr(agent, "tools", []) or []
    model_name, _ = resolve_model(agent_name)

    console.print(f"  [dim]Agent: {agent.role} | Model: {model_name}[/dim]")

    parts = []
    for event in llm_adapter.invoke_with_tools_stream(
        system_prompt=system_prompt,
        user_prompt=prompt,
        tools=tools,
        stage_name=agent_name,
        max_tool_rounds=10,
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
        r'(?:file_write|modified|changed|written)[^\n]*?([\w./-]+\.\w+)',
        output,
    ):
        files.add(m.group(1))
    return list(files)[:20]
