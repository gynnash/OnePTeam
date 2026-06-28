"""onep strategy — manage strategy analysis sessions."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from onep.persistence.database import init_db, list_projects
from onep.persistence.models import Project
from onep.strategy.models import ItemStatus
from onep.strategy.persistence import load_workbench
from onep.strategy.workbench import run_dialogue_loop

console = Console()


def _resolve_project(projects: list[Project], ref: str) -> Project | None:
    """Resolve a project by ID prefix (exact match) or by name (latest)."""
    # ID prefix match — most precise
    id_matches = [p for p in projects if p.id.startswith(ref)]
    if len(id_matches) == 1:
        return id_matches[0]
    if len(id_matches) > 1:
        console.print(f"[red]Ambiguous ID prefix. Use more characters.[/red]")
        for p in id_matches:
            console.print(f"  {p.id} — {p.name}")
        return None

    # Name match — pick latest (projects already ordered by updated_at DESC)
    name_matches = [p for p in projects if p.name == ref]
    if name_matches:
        return name_matches[0]

    return None


@click.group()
def strategy_group():
    """Manage strategy analysis sessions."""
    pass


@strategy_group.command()
@click.argument("project_ref", type=str)
def resume(project_ref: str):
    """Resume a previous strategy analysis session.

    PROJECT_REF can be a project name (latest if multiple) or an ID prefix.
    """
    init_db()
    projects = list_projects()
    project = _resolve_project(projects, project_ref)
    if project is None:
        console.print(f"[red]Project '{project_ref}' not found.[/red]")
        return
    workspace = Path(project.workspace_path)
    wb = load_workbench(workspace)
    if wb is None:
        console.print(f"[red]No strategy session found for '{project.name}'.[/red]")
        return
    console.print(f"[green]Resuming session: {project.name}[/green]")
    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
    except Exception:
        pass
    run_dialogue_loop(workspace, wb, llm_adapter=llm)


@strategy_group.command()
@click.argument("project_ref", type=str)
def status(project_ref: str):
    """Show analysis progress.

    PROJECT_REF can be a project name (latest if multiple) or an ID prefix.
    """
    init_db()
    projects = list_projects()
    project = _resolve_project(projects, project_ref)
    if project is None:
        console.print(f"[red]Project '{project_ref}' not found.[/red]")
        return
    wb = load_workbench(Path(project.workspace_path))
    if wb is None:
        console.print(f"[red]No strategy session found.[/red]")
        return
    total = len(wb.items)
    active = len([i for i in wb.items if i.status != ItemStatus.DISCARDED])
    drafted = len([i for i in wb.items if i.status == ItemStatus.PLAN_DRAFTED])
    reviewed = len([i for i in wb.items if i.status == ItemStatus.PLAN_REVIEWED])
    discarded = len([i for i in wb.items if i.status == ItemStatus.DISCARDED])
    table = Table(title=f"Strategy Analysis: {project.name}")
    table.add_column("Metric", style="cyan"); table.add_column("Value")
    for label, val in [("Source", wb.source_path), ("Total Items", str(total)),
                       ("Active", str(active)), ("Plan Drafted", str(drafted)),
                       ("Plan Reviewed", str(reviewed)), ("Discarded", str(discarded)),
                       ("Scan Complete", "yes" if wb.scan_complete else "no")]:
        table.add_row(label, val)
    console.print(table)


@strategy_group.command()
@click.argument("project_ref", type=str)
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "json"]), default="md")
@click.option("--items", "-i", default=None, help="Comma-separated item numbers")
def export(project_ref: str, fmt: str, items: str | None):
    """Export analysis results.

    PROJECT_REF can be a project name (latest if multiple) or an ID prefix.
    """
    init_db()
    projects = list_projects()
    project = _resolve_project(projects, project_ref)
    if project is None:
        console.print(f"[red]Project '{project_ref}' not found.[/red]")
        return
    wb = load_workbench(Path(project.workspace_path))
    if wb is None:
        console.print(f"[red]No strategy session found.[/red]")
        return
    active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
    selected = active
    if items:
        indices = [int(x.strip()) - 1 for x in items.split(",")]
        selected = [active[i] for i in indices if 0 <= i < len(active)]
    if fmt == "md":
        lines = [f"# Strategy Analysis: {wb.project_name}\n", f"Source: {wb.source_path}\n\n---\n"]
        emoji = {"high": "red_circle", "medium": "yellow_circle", "low": "green_circle"}
        for item in selected:
            e = emoji.get(item.impact, "white_circle")
            lines.append(f"## {e} {item.title}\n")
            lines.append(f"- **File**: {item.file_location}\n- **Tags**: {', '.join(item.tags) if item.tags else 'none'}\n- **Impact**: {item.impact}\n- **Status**: {item.status.value}\n\n{item.summary}\n")
            if item.plan_path:
                lines.append(f"Plan: {item.plan_path}\n")
            lines.append("---\n")
        console.print("".join(lines))
    else:
        import json
        console.print(json.dumps([{"id": i.id, "title": i.title, "file_location": i.file_location,
                                   "tags": i.tags, "impact": i.impact, "summary": i.summary,
                                   "status": i.status.value, "plan_path": i.plan_path}
                                  for i in selected], ensure_ascii=False, indent=2))


COMMANDS = [strategy_group]
