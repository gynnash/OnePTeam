"""onep status, pause, resume, approve, reject — pipeline control commands."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from onep.persistence.database import init_db, list_projects, update_project

console = Console()


@click.command()
def status_cmd():
    """Show pipeline progress for all projects."""
    init_db()
    projects = list_projects()

    if not projects:
        console.print("[yellow]No projects found. Create one with: onep create <requirement>[/yellow]")
        return

    for project in projects:
        state_symbol = {"running": "[cyan]▶[/cyan]", "paused": "[yellow]⏸[/yellow]",
                        "completed": "[green]✓[/green]", "failed": "[red]✗[/red]"}
        symbol = state_symbol.get(project.status.value, "?")

        console.print(Panel(
            f"{symbol} [bold]{project.name}[/bold] ({project.mode.value})\n"
            f"  Status: {project.status.value} | Stage: {project.current_stage or 'not started'}",
            title=f"Project {project.id[:8]}",
        ))


@click.command()
@click.argument("project_name", type=str)
def pause_cmd(project_name: str):
    """Pause a running pipeline."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return
    from onep.persistence.models import ProjectStatus
    project.status = ProjectStatus.PAUSED
    project.touch()
    update_project(project)
    console.print(f"[yellow]Project '{project_name}' paused.[/yellow]")


@click.command()
@click.argument("project_name", type=str)
def resume_cmd(project_name: str):
    """Resume a paused pipeline."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return
    from onep.persistence.models import ProjectStatus
    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)
    console.print(f"[green]Project '{project_name}' resumed.[/green]")


@click.command()
@click.argument("project_name", type=str)
def approve_cmd(project_name: str):
    """Approve the current approval gate and resume the pipeline."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    from pathlib import Path
    from onep.persistence.state import load_state, save_state
    from onep.persistence.models import ProjectStatus

    state = load_state(Path(project.workspace_path))
    state.pending_approval = False
    save_state(Path(project.workspace_path), state)

    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)
    console.print(f"[green]Stage approved for '{project_name}'. Run 'onep run {project_name}' to continue.[/green]")


@click.command()
@click.argument("project_name", type=str)
@click.argument("reason", type=str, default="")
def reject_cmd(project_name: str, reason: str):
    """Reject the current stage with optional feedback."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    from pathlib import Path
    from onep.persistence.state import load_state, save_state
    from onep.persistence.models import ProjectStatus

    state = load_state(Path(project.workspace_path))
    state.pending_approval = False
    save_state(Path(project.workspace_path), state)

    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)
    console.print(f"[red]Stage rejected for '{project_name}'.[/red]")
    if reason:
        console.print(f"Feedback: {reason}")


COMMANDS = [status_cmd, pause_cmd, resume_cmd, approve_cmd, reject_cmd]
