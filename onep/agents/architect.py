"""Architect Agent - designs system architecture, data models, and API contracts."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileWriteTool, FileListTool
from onep.tools.memory import MemoryTool


@register("architect")
def create_architect(workspace: str = "", source_id: str = "") -> Agent:
    tools = [MemoryTool(default_source_id=source_id)]
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileWriteTool(workspace=workspace),
            FileListTool(workspace=workspace),
            MemoryTool(default_source_id=source_id),
        ]

    return Agent(
        role="架构师",
        goal="基于 PRD 和 UI 设计稿，设计系统架构、数据模型、API 契约和技术选型",
        backstory=(
            "你是一位经验丰富的系统架构师，专注于全栈应用架构设计。"
            "你精通 Python 后端（FastAPI）、React 前端和 React Native 移动端架构。"
            "你设计 RESTful API、数据库 Schema (SQL/NoSQL)、组件树和中间件策略。"
            "你输出结构化的 ARCHITECTURE.md、Mermaid 架构图和 API 文档。"
            "你始终考虑可扩展性、安全性和性能。"
            "你可以使用 file_read 读取 PRD 和设计文档，用 file_write 输出架构文档，"
            "用 file_list 浏览项目目录结构。"
        ),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
