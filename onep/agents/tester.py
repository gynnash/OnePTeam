"""Tester Agent - writes and runs tests, validates functionality."""
from crewai import Agent

from onep.agents.registry import register


@register("tester")
def create_tester() -> Agent:
    return Agent(
        role="测试工程师",
        goal="编写并运行测试用例，验证功能正确性和代码质量",
        backstory=(
            "你是一位测试工程师，负责确保软件质量。你为后端编写 pytest 测试，"
            "为前端编写 vitest + React Testing Library 测试。"
            "你关注功能正确性、边界条件、API 契约和集成场景。"
            "MVP 阶段聚焦基础冒烟测试和关键路径验证。"
            "你每次运行测试后输出 TEST_REPORT.md。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
