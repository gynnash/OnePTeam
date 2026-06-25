"""Greenfield pipeline: PM → Designer → Architect → Developer → Tester → DevOps."""
from __future__ import annotations

from pathlib import Path

from crewai import Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


GREENFIELD_STAGES = [
    {"name": "pm", "agent": "pm", "description": "分析需求并生成 PRD"},
    {"name": "designer", "agent": "designer", "description": "设计 UI/UX 并生成设计文档"},
    {"name": "architect", "agent": "architect", "description": "设计系统架构、数据模型和 API"},
    {"name": "developer", "agent": "developer", "description": "实现后端、前端代码和 Docker 配置"},
    {"name": "tester", "agent": "tester", "description": "编写并运行测试"},
    {"name": "devops", "agent": "devops", "description": "Docker 部署和健康检查"},
]

STAGE_PROMPTS = {
    "pm": """\
你是一位产品经理。请根据以下用户需求，输出一份结构化的产品需求文档 (PRD)。

用户需求：{requirement}

请按以下结构输出 PRD 并保存为 docs/PRD.md：
1. 产品概述
2. 目标用户
3. 用户故事（至少3个）
4. 功能规格（核心功能列表，标注优先级 P0/P1/P2）
5. 验收标准（每个功能的可测量标准）
6. 非功能需求（性能、安全、兼容性）

使用中文撰写。""",

    "designer": """\
你是一位 UI/UX 设计师。请基于以下 PRD 设计用户界面和交互流程。

PRD 文档：docs/PRD.md 的内容如下：
{prd_content}

请输出设计文档并保存为 docs/DESIGN.md，包含：
1. 信息架构（页面层级关系图，用文本描述）
2. 页面清单和每个页面的布局说明
3. 核心交互流程（关键用户路径）
4. 组件清单（可复用组件列表及用途）
5. 视觉规范（颜色方案、排版层级、间距系统）

为 Web (React) 和 Mobile (React Native) 分别设计适配方案。
使用中文撰写。""",

    "architect": """\
你是一位系统架构师。请基于 PRD 和 UI 设计设计技术架构。

PRD: docs/PRD.md
UI 设计: docs/DESIGN.md

项目工作区: {workspace}

请输出架构文档 docs/ARCHITECTURE.md，并创建实际的项目代码结构：
1. 系统架构总览（文本描述各层职责）
2. 技术栈确认（FastAPI + SQLAlchemy + React + Vite）
3. 数据库 Schema 设计（建表 SQL 或 SQLAlchemy 模型定义）
4. REST API 设计（端点列表、请求/响应格式）
5. React 组件树（页面→组件层级关系）
6. 项目目录结构

使用中文撰写文档，代码标识符使用英文。""",

    "developer": """\
你是一位全栈研发工程师。请根据架构设计实现完整的应用代码。

工作区: {workspace}
架构设计: docs/ARCHITECTURE.md

请完成以下工作：
1. 创建后端项目结构 (backend/)，实现 FastAPI 应用
2. 创建前端项目结构 (frontend/)，实现 React + Vite 应用
3. 编写 Dockerfile 和 docker-compose.yml
4. 确保应用可以本地运行

代码标识符和注释使用英文。使用 git 管理版本，每完成一个模块后提交。
后端使用 FastAPI + SQLAlchemy + Pydantic。
前端使用 React + TypeScript + Vite + TailwindCSS。""",

    "tester": """\
你是一位测试工程师。请为项目编写并运行测试。

工作区: {workspace}

请完成以下工作：
1. 为后端 API 编写 pytest 测试 (backend/tests/)
2. 为前端组件编写 vitest 测试 (frontend/src/__tests__/)
3. 运行测试并收集结果
4. 输出 TEST_REPORT.md（测试概览、通过/失败列表、覆盖率）

MVP 阶段聚焦基础冒烟测试和关键 API 端点验证。""",

    "devops": """\
你是一位 DevOps 工程师。请部署应用。

工作区: {workspace}

请完成以下工作：
1. 检查 docker-compose.yml 配置是否正确
2. 运行 docker compose up -d --build
3. 等待服务启动并进行健康检查
4. 输出 DEPLOY_LOG.md 和访问地址

确认以下服务正常运行：
- 后端 API (默认 http://localhost:8000)
- 前端应用 (默认 http://localhost:5173)
- 数据库 (如果使用)""",
}


def build_greenfield_tasks(project: Project, state: PipelineState) -> list[Task]:
    """Build CrewAI Task list for the Greenfield pipeline."""
    workspace = Path(project.workspace_path)
    requirement = getattr(project, 'requirement', '')

    prd_path = workspace / "docs" / "PRD.md"
    prd_content = prd_path.read_text() if prd_path.exists() else ""

    tasks = []
    for stage in GREENFIELD_STAGES:
        prompt = STAGE_PROMPTS[stage["name"]].format(
            requirement=requirement,
            prd_content=prd_content,
            workspace=str(workspace),
        )

        task = Task(
            description=prompt,
            expected_output=f"Stage {stage['name']} completed. Output saved to workspace.",
            agent=get_agent(stage["agent"]),
        )
        tasks.append(task)

    return tasks


def get_greenfield_stages() -> list[dict]:
    """Return the list of Greenfield stages (for status display)."""
    return GREENFIELD_STAGES
