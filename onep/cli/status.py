"""onep status, pause, resume, approve, reject — pipeline control commands."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

import shutil
from pathlib import Path

from onep.persistence.database import (
    init_db, list_projects, update_project, delete_project,
    get_latest_stage_run, insert_approval,
)

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
            f"  Status: {project.status.value} | Stage: {project.current_stage or 'not started'}\n"
            f"  ID: {project.id} | Workspace: {project.workspace_path}",
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
    from onep.persistence.models import ProjectStatus, Approval, Decision

    state = load_state(Path(project.workspace_path))
    stage_run = get_latest_stage_run(project.id, project.current_stage)
    if stage_run is None or not state.pending_approval:
        console.print("[red]No pending approval found.[/red]")
        return
    insert_approval(Approval(
        stage_run_id=stage_run.id,
        decision=Decision.APPROVED,
    ))
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
    from onep.persistence.models import ProjectStatus, Approval, Decision

    state = load_state(Path(project.workspace_path))
    stage_run = get_latest_stage_run(project.id, project.current_stage)
    if stage_run is None or not state.pending_approval:
        console.print("[red]No pending approval found.[/red]")
        return
    insert_approval(Approval(
        stage_run_id=stage_run.id,
        decision=Decision.REJECTED,
        feedback=reason,
    ))
    state.pending_approval = False
    if project.current_stage in state.stages_completed:
        state.stages_completed.remove(project.current_stage)
    state.current_stage = project.current_stage
    save_state(Path(project.workspace_path), state)

    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)
    console.print(f"[red]Stage rejected for '{project_name}'.[/red]")
    if reason:
        console.print(f"Feedback: {reason}")


@click.command()
@click.argument("project_ref", type=str)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.option("--keep-files", is_flag=True, help="Keep onep workspace files on disk")
def delete_cmd(project_ref: str, force: bool, keep_files: bool):
    """Delete a project by name or ID prefix.

    PROJECT_REF can be a project name or the first few chars of its ID
    (as shown in 'onep status'). Only onep workspace files are affected;
    the original source code is never touched.
    """
    init_db()
    projects = list_projects()

    # try name match (all), then ID prefix match (single)
    name_matches = [p for p in projects if p.name == project_ref]
    if name_matches:
        targets = name_matches
    else:
        id_matches = [p for p in projects if p.id.startswith(project_ref)]
        if len(id_matches) == 1:
            targets = id_matches
        elif len(id_matches) > 1:
            console.print(f"[red]Ambiguous ID prefix. Matching projects:[/red]")
            for p in id_matches:
                console.print(f"  {p.id} — {p.name}")
            return
        else:
            targets = []

    if not targets:
        console.print(f"[red]Project '{project_ref}' not found. Use 'onep status' to list.[/red]")
        return

    if not force:
        count = len(targets)
        msg = f"Delete {count} project(s) named '{project_ref}'?"
        for p in targets:
            msg += f"\n  {p.id[:8]} — workspace: {p.workspace_path}"
        msg += "\nThe original source code is never touched."
        confirm = click.confirm(msg)
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            return

    for project in targets:
        if not keep_files:
            ws = Path(project.workspace_path)
            if ws.exists():
                shutil.rmtree(ws)
        delete_project(project.id)

    console.print(f"[green]{len(targets)} project(s) deleted.[/green]")


COMMANDS = [status_cmd, pause_cmd, resume_cmd, approve_cmd, reject_cmd, delete_cmd]
