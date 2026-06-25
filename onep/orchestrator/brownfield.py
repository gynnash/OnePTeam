"""Brownfield pipeline — analyze existing codebases."""
from __future__ import annotations

from crewai import Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


BROWNFIELD_STAGES = [
    {"name": "analyzer", "agent": "strategy_architect", "description": "策略分析"},
]


def build_brownfield_tasks(project: Project, state: PipelineState) -> list[Task]:
    tasks = []
    for stage in BROWNFIELD_STAGES:
        task = Task(
            description=f"Execute strategy analysis for project {project.name}",
            expected_output=f"Stage {stage['name']} completed.",
            agent=get_agent(stage["agent"]),
        )
        tasks.append(task)
    return tasks
