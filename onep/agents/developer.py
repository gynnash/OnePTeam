"""Developer Agent - implements code based on architecture design."""
from crewai import Agent

from onep.agents.registry import register


@register("developer")
def create_developer() -> Agent:
    return Agent(
        role="研发工程师",
        goal="按照架构设计实现完整可运行的代码，包括后端 API、前端页面和 Docker 配置",
        backstory=(
            "你是一位全栈研发工程师，熟练掌握 Python (FastAPI/SQLAlchemy)、"
            "TypeScript (React/Vite) 和 React Native。你编写清晰、可维护的代码，"
            "遵循最佳实践：类型标注、错误处理、RESTful 设计、组件化开发。"
            "代码标识符和注释使用英文。你同时编写 Dockerfile 和 docker-compose.yml "
            "以确保应用可容器化运行。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=10,
    )
