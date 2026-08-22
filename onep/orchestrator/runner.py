"""Resolve a project and run the durable autonomous harness."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from onep.harness.engine import HarnessEngine
from onep.persistence.database import init_db, list_projects
from onep.persistence.state import load_state


console = Console()


def run_pipeline(
    project_name: str,
    start_from: Optional[str] = None,
    options=None,
) -> bool:
    """Execute or resume the single durable autonomous development loop."""
    init_db()
    project = next(
        (item for item in list_projects() if item.name == project_name), None
    )
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return False
    if start_from:
        console.print(
            f"[yellow]--stage {start_from} is ignored; resuming from the durable checkpoint.[/yellow]"
        )
    if options is None:
        from onep.greenfield.models import GreenfieldOptions

        state = load_state(Path(project.workspace_path))
        options = GreenfieldOptions.from_dict(
            state.artifacts.get("greenfield_options"),
            migrate_legacy=int(
                state.artifacts.get("greenfield_options_schema") or 1
            ) < 2,
        )
    from onep.llm.router import model_overrides

    with model_overrides(options):
        return HarnessEngine(console).run(project, options)
