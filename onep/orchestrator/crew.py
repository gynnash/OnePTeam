"""Crew factory that builds a CrewAI Crew from pipeline definitions."""
from __future__ import annotations

from pathlib import Path

from crewai import Crew, Process

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


def create_crew(project: Project, state: PipelineState) -> Crew:
    """Build a Crew based on project mode."""
    if project.mode.value == "greenfield":
        from onep.orchestrator.greenfield import build_greenfield_tasks
        tasks = build_greenfield_tasks(project, state)
    else:
        from onep.orchestrator.brownfield import build_brownfield_tasks
        tasks = build_brownfield_tasks(project, state)

    # Agents are attached to tasks directly; no separate agents list needed.
    agents: list = []

    return Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )
