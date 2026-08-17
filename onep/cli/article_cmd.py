"""onep article — synthesize a knowledge article for a completed project."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from onep.harness.article import ArticleSynthesizer
from onep.harness.persistence import load_harness_run
from onep.harness.vault import VaultWriter, global_vault_root
from onep.llm.adapters import LLMAdapter
from onep.persistence.database import init_db, list_projects

console = Console()


@click.command()
@click.argument("project", type=str)
def article_cmd(project: str) -> None:
    """Synthesize a knowledge article from a harness project's records."""
    init_db()
    proj = next((p for p in list_projects() if p.name == project), None)
    if proj is None:
        console.print(
            f"[red]Project '{project}' not found. Run 'onep status' "
            f"to list projects.[/red]"
        )
        return
    workspace = Path(proj.workspace_path).resolve()
    run = load_harness_run(workspace)
    if run is None:
        console.print(
            f"[yellow]No harness run found for '{project}' at {workspace}.[/yellow]"
        )
        return
    if run.mode == "greenfield" and run.greenfield_run is not None:
        run_dir = (
            workspace / ".onep" / "greenfield"
            / "runs" / run.greenfield_run.id
        )
    else:
        run_dir = workspace / ".onep" / "optimize" / "runs" / run.id
    writer = VaultWriter(global_vault_root())
    synthesizer = ArticleSynthesizer(LLMAdapter(), writer)
    console.print(f"[cyan]Synthesizing article for '{project}'...[/cyan]")
    result = synthesizer.synthesize(workspace, run_dir, run)
    console.print(
        f"[bold green]Article:[/bold green] {result['article_path']}\n"
        f"[bold green]Reasoning graph:[/bold green] {result['graph_path']}\n"
        f"[dim]{result['title']}[/dim]"
    )


COMMANDS = [article_cmd]
