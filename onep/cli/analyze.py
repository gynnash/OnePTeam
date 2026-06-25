"""onep analyze — analyze existing codebases for strategy optimizations."""
from __future__ import annotations

import json
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
from onep.strategy.scanner import walk_files, batch_files, parse_scan_response, get_strategy_files
from onep.strategy.analyzer import parse_analysis_response
from onep.strategy.persistence import save_workbench
from onep.strategy.workbench import run_dialogue_loop
from onep.agents.registry import get_agent
from onep.orchestrator.brownfield import SCAN_PROMPT, ANALYZE_PROMPT

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
        subprocess.run(["git", "clone", "--depth", "1", source, str(tmpdir)],
                       check=True, capture_output=True)
        return tmpdir
    return Path(source).resolve()


def _build_agent_system_prompt(agent_name: str) -> str:
    """Build a system prompt from an agent's registered role, goal, and backstory."""
    agent = get_agent(agent_name)
    return f"""{agent.role}

目标: {agent.goal}

背景: {agent.backstory}

请按照用户指令完成工作，只输出要求的内容，不要额外解释。"""


def _invoke_agent(agent_name: str, user_prompt: str) -> str | None:
    """Invoke an agent via the LLM adapter with its full persona as system prompt."""
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
        return llm.invoke(
            system_prompt=_build_agent_system_prompt(agent_name),
            user_prompt=user_prompt,
            stage_name=agent_name,
        )
    except Exception as e:
        console.print(f"[yellow]LLM 调用失败: {e}[/yellow]")
        return None


def _run_strategy_mode(source_path: Path, workspace: Path, project_name: str) -> None:
    # ------- Layer 1: Scan -------
    console.print("\n[bold cyan]=== Layer 1: 快速扫描 ===[/bold cyan]")
    console.print("[dim]代码分析师 Agent 扫描中...[/dim]")

    all_files = walk_files(source_path)
    batches = batch_files(all_files)
    all_results = []

    for i, batch in enumerate(batches):
        relative_paths = [str(f.relative_to(source_path)) for f in batch]
        prompt = SCAN_PROMPT.format(file_list="\n".join(relative_paths))

        response = _invoke_agent("analyzer", prompt)
        if response:
            batch_results = parse_scan_response(response)
        else:
            batch_results = [
                _no_llm_scan_result(str(f.relative_to(source_path)))
                for f in batch
            ]
        all_results.extend(batch_results)

        if len(batches) > 1:
            console.print(f"  [dim]批次 {i + 1}/{len(batches)} 完成[/dim]")

    strategy_files = get_strategy_files(all_results)
    console.print(f"扫描完成: {len(all_files)} 个文件, {len(strategy_files)} 个策略密集文件")

    # ------- Layer 2: Analyze -------
    console.print("\n[bold cyan]=== Layer 2: 深度分析 ===[/bold cyan]")
    console.print("[dim]策略架构师 Agent 分析中...[/dim]")

    if strategy_files:
        prompt = ANALYZE_PROMPT.format(
            file_list="\n".join(f"- {f}" for f in strategy_files),
            source_root=str(source_path),
        )
        response = _invoke_agent("strategy_architect", prompt)
        items = parse_analysis_response(response) if response else _no_llm_items()
    else:
        items = [
            _no_llm_item("未发现策略密集文件，建议检查代码库内容或手动指定分析范围。")
        ]

    console.print(f"分析完成: 发现 {len(items)} 个优化方向")

    # ------- Display & Save -------
    wb = WorkbenchState(
        project_name=project_name, source_path=str(source_path),
        items=items, scan_complete=True, analysis_complete=True,
    )

    for i, item in enumerate(items, 1):
        color = {"high": "red", "medium": "yellow", "low": "dim"}.get(item.impact, "white")
        tags_str = f" [{', '.join(item.tags)}]" if item.tags else ""
        console.print(
            f"  [{i}] [{color}]{item.title}[/{color}] — "
            f"{item.file_location}{tags_str} — 影响: {item.impact}"
        )

    save_workbench(workspace, wb)

    # ------- Layer 3: Dialogue -------
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


def _no_llm_scan_result(file_path: str):
    """Fallback scan result when LLM is unavailable."""
    from onep.strategy.scanner import ScanResult
    return ScanResult(
        file_path=file_path,
        is_strategy=True,
        reason="LLM不可用，默认标记为策略文件待人工审查",
    )


def _no_llm_items() -> list:
    """Fallback items when LLM is unavailable."""
    return [_no_llm_item("请配置 API 密钥后重新运行分析。")]


def _no_llm_item(message: str):
    """Single fallback StrategyItem."""
    from onep.strategy.models import StrategyItem
    return StrategyItem(
        title="LLM不可用，策略分析待执行",
        file_location="N/A",
        summary=message,
        tags=["系统"],
        impact="high",
    )


COMMANDS = [analyze_cmd]
