"""onep export — export analysis results as Markdown or JSON."""
from __future__ import annotations

from pathlib import Path
import json

import click
from rich.console import Console

from onep.persistence.database import init_db, list_projects
from onep.strategy.persistence import load_workbench
from onep.strategy.scanner import load_batch_results as load_analysis_items_from_jsonl

console = Console()


def _build_markdown(project_name: str, source_path: str, items: list[dict]) -> str:
    lines = [
        f"# 策略分析报告: {project_name}",
        "",
        "## 概览",
        f"- 源路径: {source_path}",
        f"- 发现优化方向: {len(items)} 个",
        "",
        "## 优化方向",
        "",
    ]
    for i, item in enumerate(items, 1):
        impact = item.get("impact", "?")
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "⚪")
        lines.append(f"### {i}. {emoji} [{impact}] {item.get('title', '?')}")
        lines.append(f"- **文件**: {item.get('file_location', '?')}")
        tags = item.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = [tags]
        lines.append(f"- **标签**: {', '.join(tags) if tags else '无'}")
        lines.append(f"- **摘要**: {item.get('summary', '?')}")
        plan = item.get("plan_path", "")
        if plan:
            lines.append(f"- **Plan**: {plan}")
        lines.append("")

    lines.extend(["## 附录", "",
                  f"- 导出时间: {__import__('datetime').datetime.now().isoformat()}"])
    return "\n".join(lines)


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

    if fmt == "json":
        content = json.dumps({"project": project, "source_path": source_path,
                              "items": items}, ensure_ascii=False, indent=2)
    else:
        content = _build_markdown(project, source_path, items)

    if output:
        Path(output).write_text(content)
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


COMMANDS = [export_group]
