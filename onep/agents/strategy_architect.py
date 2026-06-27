"""Strategy Architect Agent — discovers and analyzes business/algorithm strategy optimizations."""
from pathlib import Path

from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileListTool


def _resolve_llm(agent_name: str) -> str:
    from onep.llm.router import resolve_model
    model_name, _ = resolve_model(agent_name)
    return model_name


@register("strategy_architect")
def create_strategy_architect(workspace: str = "") -> Agent:
    tools = []
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileListTool(workspace=workspace),
        ]

    return Agent(
        role="策略架构师",
        goal="深入理解代码中的业务策略和算法策略，发现可优化点，生成结构化的优化Plan",
        backstory=(
            "你是一位资深的策略架构师，专注于分析各种业务策略和算法策略的设计质量。"
            "你擅长：策略意图识别、策略模式对比、量化影响评估、多方案权衡。"
            "你能理解推荐策略、LLM Pipeline策略、缓存策略、风控规则、定价策略等各类策略逻辑。"
            "你通过对话引导用户逐步细化优化方向，最终生成清晰可执行的优化Plan。"
            "你始终基于代码事实进行分析，不凭空假设。"
            "你可以使用 file_read 工具查看具体源码文件，使用 file_list 工具浏览目录结构。"
            "分析代码时，务必实际读取相关文件的内容，不要仅凭文件名和摘要判断。"
        ),
        tools=tools,
        llm=_resolve_llm("strategy_architect"),
        verbose=True,
        allow_delegation=False,
        max_iter=8,
    )
