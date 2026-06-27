"""onep memory — manage the memory system."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from onep.memory.schema import init_memory_db
from onep.memory.manager import MemoryManager

console = Console()


@click.group()
def memory_group():
    """Manage the persistent memory system."""
    init_memory_db()


@memory_group.command()
def status():
    """Show memory system statistics."""
    mgr = MemoryManager()
    s = mgr.status()
    table = Table(title="Memory System Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Database", s["db_path"])
    table.add_row("Total Entries", str(s["total_entries"]))
    for src in s["sources"]:
        table.add_row(f"  Source: {src['source_id']}", str(src["count"]))
    console.print(table)


@memory_group.command()
@click.argument("query", type=str)
@click.option("--top", "-n", default=10, help="Max results")
def search(query: str, top: int):
    """Search memories by keyword or semantic query."""
    mgr = MemoryManager()
    results = mgr.search(query, top_k=top)
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return
    for r in results:
        source = r.get("source_id", "?")
        title = r.get("title", "?")
        score = r.get("score", 0)
        tags = r.get("tags", "[]")
        console.print(f"  [{source}] [bold]{title}[/bold] (score: {score:.2f})")
        console.print(f"  tags: {tags}\n")


@memory_group.command()
@click.argument("project", type=str)
@click.option("--all", "-a", "all_projects", is_flag=True, help="Import all projects")
def import_cmd(project: str, all_projects: bool):
    """Import memories from project dialogue and workbench files."""
    if all_projects:
        console.print("[yellow]--all not yet implemented[/yellow]")
        return
    mgr = MemoryManager()
    from pathlib import Path
    from onep.strategy.persistence import load_workbench
    from onep.persistence.database import init_db, list_projects
    init_db()
    projects = list_projects()
    proj = next((p for p in projects if p.name == project), None)
    if proj is None:
        console.print(f"[red]Project '{project}' not found. Run 'onep status' to list.[/red]")
        return
    wb = load_workbench(Path(proj.workspace_path))
    if wb is None:
        console.print(f"[yellow]No workbench found for '{project}'.[/yellow]")
        return
    count = 0
    for item in wb.items:
        mgr.capture(
            source_id=f"brownfield:{project}",
            title=item.title,
            content=item.summary,
            importance=5,
        )
        count += 1
    if wb.dialogue:
        mgr.capture(
            source_id=f"brownfield:{project}",
            title=f"对话记录 — {project}",
            content="\n".join(t.content[:200] for t in wb.dialogue[-10:]),
            importance=3,
        )
        count += 1
    console.print(f"[green]Imported {count} memories from '{project}'.[/green]")


@memory_group.command()
@click.option("--older-than", type=int, default=90, help="Days old")
def clean(older_than: int):
    """Remove low-score decayed memories."""
    mgr = MemoryManager()
    removed = mgr.clean(min_score=0.1)
    console.print(f"[green]Cleaned {removed} low-score memories.[/green]")


COMMANDS = [memory_group]
