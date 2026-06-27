"""onep optimize -- automated optimize loop with safety gates."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from onep.config import load_config
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.strategy.models import classify_impact
from onep.strategy.scanner import walk_files, batch_files, parse_scan_response, get_strategy_files
from onep.strategy.analyzer import parse_analysis_response
from onep.strategy.optimize_engine import OptimizeEngine
from onep.llm.cost import CostTracker

console = Console()


@click.command()
@click.argument("source", type=str)
@click.option("--max-rounds", type=int, default=5)
@click.option("--auto-approve", default="low,medium",
              help="Impact levels to auto-execute (comma-separated)")
@click.option("--max-cost", type=float, default=0)
@click.option("--name", "-n", default=None)
def optimize_cmd(source: str, max_rounds: int, auto_approve: str,
                 max_cost: float, name: str | None):
    """Automated optimize loop: analyze, plan, develop, test, repeat."""
    source_path = Path(source).resolve()
    if name is None:
        clean = re.sub(r'[^\w]', '', source_path.name)[:20]
        name = clean or f"optimize-{uuid.uuid4().hex[:6]}"

    config = load_config()
    init_db()
    project_root = Path(os.path.expanduser(config.project.root_dir))
    workspace = (project_root / "projects" / name / "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    project = Project(name=name, mode=ProjectMode.BROWNFIELD,
                      workspace_path=str(workspace))
    insert_project(project)

    auto_levels = set(auto_approve.split(","))

    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
    except Exception:
        pass

    tracker = CostTracker(budget=max_cost)
    engine = OptimizeEngine()

    skipped: list[dict] = []
    completed: list[dict] = []
    failed: list[dict] = []
    log_path = workspace / "optimize_log.jsonl"

    for round_num in range(1, max_rounds + 1):
        console.print(f"\n[bold]=== Round {round_num}/{max_rounds} ===[/bold]")

        # Analyze -- Layer 1 scan
        all_files = walk_files(source_path)
        batches = batch_files(all_files)
        all_results = []
        for batch in batches:
            prompt = _build_scan_prompt(batch, source_path)
            response = _invoke_llm(llm, "analyzer", prompt)
            if response:
                all_results.extend(parse_scan_response(response))
        strategy_files = get_strategy_files(all_results)

        if not strategy_files:
            console.print("[green]No more targets.[/green]")
            break

        # Analyze -- Layer 2
        analyze_prompt = _build_analyze_prompt(strategy_files, str(source_path))
        response = _invoke_llm(llm, "strategy_architect", analyze_prompt)
        items = parse_analysis_response(response) if response else []

        if not items:
            break

        round_done = 0
        for item_data in items:
            item = _dict_to_item(item_data)
            impact = classify_impact(item.title, item.summary, item.tags)

            if impact not in auto_levels:
                skipped.append({"title": item.title, "impact": impact, "round": round_num})
                console.print(f"  [yellow]skipped (impact={impact}): {item.title}[/yellow]")
                continue

            if not tracker.can_continue():
                console.print(f"[red]Budget exhausted ({tracker.summary()})[/red]")
                break

            console.print(f"  [cyan]Executing: {item.title} (impact={impact})[/cyan]")
            result = engine.execute(item, str(source_path), str(workspace), llm)

            if result["success"]:
                completed.append({"title": item.title, "impact": impact, "round": round_num})
                round_done += 1
            else:
                failed.append({"title": item.title, "impact": impact, "round": round_num,
                              "error": result.get("error", "unknown")})

            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps({"round": round_num, "item": item.title,
                                    "impact": impact, "success": result["success"],
                                    "cost": tracker.spent}, ensure_ascii=False) + "\n")

        console.print(f"  [dim]Round {round_num}: {round_done} done, "
                      f"{len(skipped)} skipped, {tracker.summary()}[/dim]")

        if round_done == 0 and not skipped:
            break

    _generate_report(workspace, completed, failed, skipped, tracker)


def _invoke_llm(llm, agent_name: str, prompt: str) -> str | None:
    if llm is None:
        return None
    try:
        return llm.invoke(
            system_prompt=f"You are the {agent_name} agent.",
            user_prompt=prompt, stage_name=agent_name,
        )
    except Exception:
        return None


def _dict_to_item(d: dict):
    from onep.strategy.models import StrategyItem
    return StrategyItem(
        title=d.get("title", "?"),
        file_location=d.get("file_location", "?"),
        summary=d.get("summary", ""),
        tags=d.get("tags", []),
        impact=d.get("impact", "medium"),
    )


def _build_scan_prompt(batch: list, source_path: Path) -> str:
    from onep.orchestrator.brownfield import SCAN_PROMPT
    relative = [str(f.relative_to(source_path)) for f in batch]
    return SCAN_PROMPT.format(file_list="\n".join(relative))


def _build_analyze_prompt(strategy_files: list, source_root: str) -> str:
    from onep.orchestrator.brownfield import ANALYZE_PROMPT
    return ANALYZE_PROMPT.format(
        file_list="\n".join(f"- {f}" for f in strategy_files),
        source_root=source_root,
    )


def _generate_report(workspace: Path, completed: list, failed: list,
                     skipped: list, tracker: CostTracker):
    lines = [
        "# Optimize Report",
        f"- Completed: {len(completed)}",
        f"- Failed: {len(failed)}",
        f"- Skipped (needs review): {len(skipped)}",
        f"- Cost: {tracker.summary()}",
        "",
    ]
    if completed:
        lines.append("## Completed")
        for c in completed:
            lines.append(f"- [{c['impact']}] {c['title']}")
    if failed:
        lines.append("\n## Failed")
        for f in failed:
            lines.append(f"- [{f['impact']}] {f['title']}: {f.get('error', '?')}")
    if skipped:
        lines.append("\n## Pending Review (high impact)")
        for s in skipped:
            lines.append(f"- [{s['impact']}] {s['title']}")

    report = "\n".join(lines)
    path = workspace / "optimize_report.md"
    path.write_text(report)
    console.print(Panel(report, title="Optimize Report"))


COMMANDS = [optimize_cmd]
