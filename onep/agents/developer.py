"""Developer Agent - implements code based on architecture design."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileWriteTool, FileListTool
from onep.tools.shell import ShellTool
from onep.tools.lint import LintTool
from onep.tools.memory import MemoryTool


@register("developer")
def create_developer(workspace: str = "", source_id: str = "") -> Agent:
    tools = [MemoryTool(default_source_id=source_id)]
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileWriteTool(workspace=workspace),
            FileListTool(workspace=workspace),
            ShellTool(workspace=workspace),
            LintTool(workspace=workspace),
            MemoryTool(default_source_id=source_id),
        ]

    return Agent(
        role="研发工程师",
        goal="按照架构设计实现完整可运行的代码，包括后端 API、前端页面和 Docker 配置",
        backstory=(
            "你是一位全栈研发工程师，熟练掌握 Python (FastAPI/SQLAlchemy)、"
            "TypeScript (React/Vite) 和 React Native。你编写清晰、可维护的代码，"
            "遵循最佳实践：类型标注、错误处理、RESTful 设计、组件化开发。"
            "代码标识符和注释使用英文。你同时编写 Dockerfile 和 docker-compose.yml "
            "以确保应用可容器化运行。"
            "你可以使用 file_read 读取架构文档，用 file_write 创建代码文件，"
            "用 file_list 浏览项目结构，用 shell 运行命令验证代码，用 lint 检查代码质量。"
        ),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=10,
    )
