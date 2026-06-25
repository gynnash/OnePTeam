"""onep show — display pipeline artifacts."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown

from onep.persistence.database import init_db, list_projects

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def show_group(ctx):
    """View project artifacts (prd, design, architecture, report, log)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@show_group.command()
@click.argument("project_name", type=str)
def prd(project_name: str):
    """Show the PRD for a project."""
    _show_artifact(project_name, "docs/PRD.md", "PRD")


@show_group.command()
@click.argument("project_name", type=str)
def design(project_name: str):
    """Show the UI/UX design document."""
    _show_artifact(project_name, "docs/DESIGN.md", "Design")


@show_group.command()
@click.argument("project_name", type=str)
def architecture(project_name: str):
    """Show the architecture document."""
    _show_artifact(project_name, "docs/ARCHITECTURE.md", "Architecture")


@show_group.command()
@click.argument("project_name", type=str)
def report(project_name: str):
    """Show the test report."""
    _show_artifact(project_name, "docs/TEST_REPORT.md", "Test Report")


@show_group.command()
@click.argument("project_name", type=str)
def log(project_name: str):
    """Show the deployment log."""
    _show_artifact(project_name, "docs/DEPLOY_LOG.md", "Deploy Log")


def _show_artifact(project_name: str, file_path: str, label: str):
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    workspace = Path(project.workspace_path)
    target = workspace / file_path
    if not target.exists():
        console.print(f"[yellow]{label} not found: {file_path}[/yellow]")
        return

    console.print(Markdown(target.read_text()))


COMMANDS = [show_group]
