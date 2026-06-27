"""UI/UX Designer Agent - designs pages, interactions, and components."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.memory import MemoryTool


@register("designer")
def create_designer(workspace: str = "", source_id: str = "") -> Agent:
    return Agent(
        role="UI/UX 设计师",
        goal="基于产品需求设计页面布局、交互流程、组件选型和视觉规范",
        backstory=(
            "你是一位资深 UI/UX 设计师，擅长将 PRD 转化为具体的界面设计方案。"
            "你关注用户体验、视觉层次、交互逻辑和组件复用。"
            "你为 Web 和移动端设计，遵循现代设计系统规范（间距、颜色、排版）。"
            "你使用中文撰写设计文档。"
        ),
        tools=[MemoryTool(default_source_id=source_id)],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
