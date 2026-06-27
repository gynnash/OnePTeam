"""Product Manager Agent - analyzes requirements and produces PRD."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.memory import MemoryTool


@register("pm")
def create_pm(workspace: str = "", source_id: str = "") -> Agent:
    return Agent(
        role="产品经理",
        goal="将用户需求转化为结构化产品需求文档 (PRD)，包含用户故事、功能规格和验收标准",
        backstory=(
            "你是一位经验丰富的产品经理，专注于将模糊的用户需求转化为清晰可执行的产品规格。"
            "你擅长用户故事分解、功能边界定义和验收标准编写。"
            "你始终用中文撰写文档，确保内容结构化、可量化、无歧义。"
        ),
        tools=[MemoryTool(default_source_id=source_id)],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
