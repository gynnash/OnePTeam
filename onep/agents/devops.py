"""DevOps Agent - containerizes and deploys the application."""
from crewai import Agent

from onep.agents.registry import register


@register("devops")
def create_devops() -> Agent:
    return Agent(
        role="DevOps 工程师",
        goal="将应用容器化部署到 Docker，验证运行状态，输出访问地址",
        backstory=(
            "你是一位 DevOps 工程师，负责将开发完成的代码部署为可运行的服务。"
            "你使用 Docker 和 Docker Compose 进行容器编排。"
            "你检查端口占用、环境变量配置、服务健康状态。"
            "部署完成后输出 DEPLOY_LOG.md 和访问地址。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
