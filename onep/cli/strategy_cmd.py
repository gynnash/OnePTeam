"""onep strategy — manage strategy analysis sessions."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from onep.persistence.database import init_db, list_projects
from onep.strategy.models import ItemStatus
from onep.strategy.persistence import load_workbench
from onep.strategy.workbench import run_dialogue_loop

console = Console()


@click.group()
def strategy_group():
    """Manage strategy analysis sessions."""
    pass


@strategy_group.command()
@click.argument("project_name", type=str)
def resume(project_name: str):
    """Resume a previous strategy analysis session."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return
    workspace = Path(project.workspace_path)
    wb = load_workbench(workspace)
    if wb is None:
        console.print(f"[red]No strategy session found for '{project_name}'.[/red]")
        return
    console.print(f"[green]恢复会话: {project_name}[/green]")
    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
    except Exception:
        pass
    run_dialogue_loop(workspace, wb, llm_adapter=llm)


@strategy_group.command()
@click.argument("project_name", type=str)
def status(project_name: str):
    """Show analysis progress."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
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
    table = Table(title=f"策略分析: {project_name}")
    table.add_column("指标", style="cyan"); table.add_column("数值")
    for label, val in [("源路径", wb.source_path), ("优化点总数", str(total)),
                       ("活跃中", str(active)), ("Plan 已生成", str(drafted)),
                       ("Plan 已审核", str(reviewed)), ("已忽略", str(discarded)),
                       ("扫描完成", "✓" if wb.scan_complete else "○")]:
        table.add_row(label, val)
    console.print(table)


@strategy_group.command()
@click.argument("project_name", type=str)
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "json"]), default="md")
@click.option("--items", "-i", default=None, help="Comma-separated item numbers")
def export(project_name: str, fmt: str, items: str | None):
    """Export analysis results."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project not found.[/red]")
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
        lines = [f"# 策略分析报告: {wb.project_name}\n", f"源路径: {wb.source_path}\n\n---\n"]
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for item in selected:
            e = emoji.get(item.impact, "⚪")
            lines.append(f"## {e} {item.title}\n")
            lines.append(f"- **文件位置**: {item.file_location}\n- **标签**: {', '.join(item.tags) if item.tags else '无'}\n- **影响**: {item.impact}\n- **状态**: {item.status.value}\n\n{item.summary}\n")
            if item.plan_path:
                lines.append(f"📋 Plan: {item.plan_path}\n")
            lines.append("---\n")
        console.print("".join(lines))
    else:
        import json
        console.print(json.dumps([{"id": i.id, "title": i.title, "file_location": i.file_location,
                                   "tags": i.tags, "impact": i.impact, "summary": i.summary,
                                   "status": i.status.value, "plan_path": i.plan_path}
                                  for i in selected], ensure_ascii=False, indent=2))


COMMANDS = [strategy_group]
