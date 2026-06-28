"""onep export — export analysis results as Markdown or JSON."""
from __future__ import annotations

from pathlib import Path
import click
from rich.console import Console

from onep.persistence.database import init_db, list_projects
from onep.strategy.persistence import load_workbench
from onep.strategy.scanner import load_analysis_items as load_analysis_items_from_jsonl
from onep.strategy.reporting import AnalysisReport, AnalysisReportService

console = Console()


def _build_markdown(project_name: str, source_path: str, items: list[dict]) -> str:
    return AnalysisReportService().render(
        AnalysisReport(project_name, source_path, items=items), "md"
    )


@click.command()
@click.argument("project", type=str)
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "json"]), default="md")
def export_group(project: str, output: str | None, fmt: str):
    """Export analysis results for a project."""
    init_db()
    projects = list_projects()
    proj = next((p for p in projects if p.name == project), None)
    if proj is None:
        console.print(f"[red]Project '{project}' not found.[/red]")
        return

    ws = Path(proj.workspace_path)
    wb = load_workbench(ws)
    items = load_analysis_items_from_jsonl(ws)

    if not items and wb:
        items = [
            {"title": i.title, "file_location": i.file_location,
             "tags": i.tags, "impact": i.impact, "summary": i.summary,
             "plan_path": i.plan_path}
            for i in wb.items
        ]

    if not items:
        console.print("[yellow]No analysis results to export.[/yellow]")
        return

    source_path = wb.source_path if wb else "unknown"

    service = AnalysisReportService()
    report = service.from_items(project, source_path, items)
    content = service.render(report, fmt)

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


COMMANDS = [export_group]
