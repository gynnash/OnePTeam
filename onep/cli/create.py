"""onep create and onep run — create and execute projects."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from onep.config import load_config
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode, PipelineState
from onep.persistence.state import save_state
from onep.orchestrator.greenfield import GREENFIELD_STAGES
from onep.tools.git import GitTool

console = Console()


@click.command()
@click.argument("requirement", type=str)
@click.option("--name", "-n", default=None, help="Project name")
def create_cmd(requirement: str, name: str | None):
    """Create a new project from a natural language requirement."""
    config = load_config()
    init_db()

    if name is None:
        clean = re.sub(r'[^\w一-鿿]', '', requirement)[:20]
        name = clean or f"project-{uuid.uuid4().hex[:6]}"

    project_root = Path(os.path.expanduser(config.project.root_dir))
    projects_dir = project_root / "projects" / name
    workspace = projects_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    git = GitTool(workspace=workspace)
    git.init()
    (workspace / "docs").mkdir(exist_ok=True)
    (workspace / "README.md").write_text(f"# {name}\n\n{requirement}\n")
    git.add(["README.md"])
    git.commit("chore: initial commit from onep create")

    project = Project(
        name=name,
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace),
    )
    project.requirement = requirement  # type: ignore[attr-defined]
    insert_project(project)

    state = PipelineState()
    save_state(workspace, state)

    console.print(Panel.fit(
        f"[bold green]Project '{name}' created![/bold green]\n"
        f"Workspace: {workspace}\n"
        f"Mode: Greenfield (6 stages)\n\n"
        f"Run [bold cyan]onep run {name}[/bold cyan] to start the pipeline.",
        title="OnePTeam",
    ))

    console.print("\n[bold]Pipeline stages:[/bold]")
    for i, stage in enumerate(GREENFIELD_STAGES, 1):
        console.print(f"  {i}. {stage['agent']} — {stage['description']}")


@click.command()
@click.argument("project_name", type=str)
@click.option("--stage", "-s", default=None, help="Stage to resume from")
def run_cmd(project_name: str, stage: str | None):
    """Run the pipeline for a project."""
    from onep.orchestrator.runner import run_pipeline
    success = run_pipeline(project_name, start_from=stage)
    if success:
        console.print("[bold green]Pipeline completed![/bold green]")
    else:
        console.print("[yellow]Pipeline paused or failed. Check: onep status[/yellow]")


COMMANDS = [create_cmd, run_cmd]
