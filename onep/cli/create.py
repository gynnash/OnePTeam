"""onep create and onep run — create and execute projects."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from onep.application.projects import (
    create_project,
    default_project_name as default_project_name,
)
from onep.domain import Problem

console = Console()


@click.command()
@click.argument("requirement", type=str)
@click.option("--name", "-n", default=None, help="Project name")
@click.option("--no-run", is_flag=True, help="Initialize without running")
@click.option("--max-rounds", type=click.IntRange(1), default=100, show_default=True)
@click.option("--max-repairs-per-slice", type=click.IntRange(1), default=8, show_default=True)
@click.option("--max-cost", type=click.FloatRange(min=0), default=0, show_default=True)
@click.option("--test-command", "test_commands", multiple=True, help="Mandatory quality gate; repeatable")
@click.option("--deploy-mode", type=click.Choice(["verify", "local", "none"]), default="verify", show_default=True)
@click.option("--non-interactive", is_flag=True, help="Persist blockers instead of prompting")
@click.option("--verbose", is_flag=True, help="Show detailed traces")
def create_cmd(requirement, name, no_run, max_rounds, max_repairs_per_slice,
               max_cost, test_commands, deploy_mode, non_interactive, verbose):
    """Create a project and start the autonomous engineering loop."""
    from onep.greenfield.models import GreenfieldOptions
    options = GreenfieldOptions(
        max_rounds=max_rounds,
        max_repairs_per_slice=max_repairs_per_slice,
        max_cost=max_cost,
        test_commands=list(test_commands),
        deploy_mode=deploy_mode,
        non_interactive=non_interactive,
        verbose=verbose,
    )
    try:
        project = create_project(requirement, name=name, options=options)
    except Problem as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(Panel.fit(
        f"[bold green]Project '{project.name}' created![/bold green]\n"
        f"Workspace: {project.workspace_path}\n"
        f"Mode: Greenfield autonomous loop\n\n"
        + (f"Run [bold cyan]onep run {project.name}[/bold cyan] to start."
           if no_run else "Starting autonomous engineering loop..."),
        title="OnePTeam",
    ))
    if not no_run:
        from onep.orchestrator.runner import run_pipeline
        if not run_pipeline(project.name, options=options):
            raise click.ClickException(
                f"Run did not complete. Resume with: onep run {project.name}"
            )

@click.command()
@click.argument("project_name", type=str)
@click.option("--stage", "-s", default=None, help="Legacy checkpoint hint")
def run_cmd(project_name: str, stage: str | None):
    """Run or resume the autonomous engineering loop."""
    from onep.orchestrator.runner import run_pipeline
    success = run_pipeline(project_name, start_from=stage)
    if success:
        console.print("[bold green]Pipeline completed![/bold green]")
    else:
        console.print("[yellow]Pipeline paused or failed. Check: onep status[/yellow]")


COMMANDS = [create_cmd, run_cmd]
