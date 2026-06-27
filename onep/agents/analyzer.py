"""Code Analyzer Agent — scans codebase files to identify strategy-intensive code."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileListTool
from onep.tools.memory import MemoryTool


@register("analyzer")
def create_analyzer(workspace: str = "", source_id: str = "") -> Agent:
    tools = [MemoryTool(default_source_id=source_id)]
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileListTool(workspace=workspace),
            MemoryTool(default_source_id=source_id),
        ]
    return Agent(
        role="代码分析师",
        goal="快速扫描代码库，识别包含业务策略和算法策略的密集文件，为深度分析提供候选列表",
        backstory=(
            "你是一位资深的代码分析师，擅长从大型代码库中快速识别策略密集型代码。"
            "你能够区分纯样板代码与包含非平凡决策逻辑的策略代码。"
            "你关注的策略类型包括：推荐算法、LLM Pipeline、缓存策略、业务规则、风控逻辑等。"
            "你输出简洁的 JSON 结果，每文件一行，不做多余的评论。"
        ),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
