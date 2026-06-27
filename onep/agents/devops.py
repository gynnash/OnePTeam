"""DevOps Agent - containerizes and deploys the application."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileWriteTool
from onep.tools.shell import ShellTool
from onep.tools.docker import DockerTool


@register("devops")
def create_devops(workspace: str = "") -> Agent:
    tools = []
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileWriteTool(workspace=workspace),
            ShellTool(workspace=workspace),
            DockerTool(workspace=workspace),
        ]

    return Agent(
        role="DevOps 工程师",
        goal="将应用容器化部署到 Docker，验证运行状态，输出访问地址",
        backstory=(
            "你是一位 DevOps 工程师，负责将开发完成的代码部署为可运行的服务。"
            "你使用 Docker 和 Docker Compose 进行容器编排。"
            "你检查端口占用、环境变量配置、服务健康状态。"
            "部署完成后输出 DEPLOY_LOG.md 和访问地址。"
            "你可以使用 docker 工具执行 compose up/down/ps/health，"
            "用 shell 执行必要的系统命令，"
            "用 file_read 检查 docker-compose.yml 和 Dockerfile，"
            "用 file_write 输出部署日志。"
        ),
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
