"""onep analyze — analyze existing codebases for strategy optimizations."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
import subprocess
import tempfile

import click
from rich.console import Console

from onep.config import load_config
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.strategy.models import WorkbenchState
from onep.strategy.scanner import scan_files, get_strategy_files
from onep.strategy.analyzer import analyze_strategies
from onep.strategy.persistence import save_workbench
from onep.strategy.workbench import run_dialogue_loop

console = Console()


@click.command()
@click.argument("source", type=str)
@click.option("--mode", "-m", type=click.Choice(["code", "strategy"]), default="strategy",
              help="Analysis mode")
@click.option("--name", "-n", default=None, help="Project name")
def analyze_cmd(source: str, mode: str, name: str | None):
    """Analyze a codebase for strategy optimizations.

    SOURCE can be a local path or a git repository URL.
    """
    config = load_config()
    init_db()
    source_path = _resolve_source(source)
    if name is None:
        clean = re.sub(r'[^\w一-鿿]', '', Path(source).name)[:20]
        name = clean or f"analysis-{uuid.uuid4().hex[:6]}"
    project_root = Path(os.path.expanduser(config.project.root_dir))
    workspace = (project_root / "projects" / name / "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    project = Project(name=name, mode=ProjectMode.BROWNFIELD, workspace_path=str(workspace))
    insert_project(project)
    console.print(f"[bold]Source:[/bold] {source_path}\n[bold]Workspace:[/bold] {workspace}")
    if mode == "strategy":
        _run_strategy_mode(source_path, workspace, name)
    else:
        console.print(f"[yellow]Mode '{mode}' not yet implemented.[/yellow]")


def _resolve_source(source: str) -> Path:
    if source.startswith(("http://", "https://", "git@", "ssh://")):
        tmpdir = Path(tempfile.mkdtemp(prefix="onep-clone-"))
        console.print(f"[dim]Cloning {source}...[/dim]")
        subprocess.run(["git", "clone", "--depth", "1", source, str(tmpdir)], check=True, capture_output=True)
        return tmpdir
    return Path(source).resolve()


def _run_strategy_mode(source_path: Path, workspace: Path, project_name: str) -> None:
    console.print("\n[bold cyan]=== Layer 1: 快速扫描 ===[/bold cyan]")
    results = scan_files(source_path, llm_adapter=None)
    strategy_files = get_strategy_files(results)
    console.print(f"扫描完成: {len(results)} 个文件, {len(strategy_files)} 个策略密集文件")

    console.print("\n[bold cyan]=== Layer 2: 深度分析 ===[/bold cyan]")
    items = analyze_strategies(strategy_files, source_path, llm_adapter=None)
    console.print(f"分析完成: 发现 {len(items)} 个优化方向")

    wb = WorkbenchState(project_name=project_name, source_path=str(source_path),
                        items=items, scan_complete=True, analysis_complete=True)

    for i, item in enumerate(items, 1):
        color = {"high": "red", "medium": "yellow", "low": "dim"}.get(item.impact, "white")
        tags_str = f" [{', '.join(item.tags)}]" if item.tags else ""
        console.print(f"  [{i}] [{color}]{item.title}[/{color}] — {item.file_location}{tags_str} — 影响: {item.impact}")

    save_workbench(workspace, wb)
    console.print(f"\n[bold cyan]=== Layer 3: 交互式对话 ===[/bold cyan]")

    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
    except Exception:
        pass

    wb = run_dialogue_loop(workspace, wb, llm_adapter=llm)
    console.print(f"\n[bold green]分析会话结束。[/bold green]")
    console.print(f"恢复: [bold cyan]onep strategy resume {project_name}[/bold cyan]")


COMMANDS = [analyze_cmd]
