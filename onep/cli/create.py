"""onep create and onep run — create and execute projects."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import click
import git as git_module
from rich.console import Console
from rich.panel import Panel

from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode, PipelineState
from onep.persistence.state import save_state
from onep.tools.git import GitTool

console = Console()


@click.command()
@click.argument("requirement", type=str)
@click.option("--name", "-n", default=None, help="Project name")
@click.option("--no-run", is_flag=True, help="Initialize without running")
@click.option("--max-rounds", type=click.IntRange(1), default=100, show_default=True)
@click.option("--max-repairs-per-slice", type=click.IntRange(1), default=8, show_default=True)
@click.option("--max-cost", type=click.FloatRange(min=0), default=0, show_default=True)
@click.option("--test-command", "test_commands", multiple=True, help="Mandatory quality gate; repeatable")
@click.option("--deploy-mode", type=click.Choice(["verify", "local", "none"]), default="verify", show_default=True)
@click.option("--non-interactive", is_flag=True, help="Persist blockers instead of prompting")
@click.option("--verbose", is_flag=True, help="Show detailed traces")
def create_cmd(
    requirement: str, name: str | None, no_run: bool, max_rounds: int,
    max_repairs_per_slice: int, max_cost: float,
    test_commands: tuple[str, ...], deploy_mode: str,
    non_interactive: bool, verbose: bool,
):
    """Create a project and start the autonomous engineering loop."""
    init_db()

    if name is None:
        clean = re.sub(r'[^\w一-鿿]', '', requirement)[:20]
        name = clean or f"project-{uuid.uuid4().hex[:6]}"

    workspace, repository_exists = _resolve_workspace(Path.cwd())

    git_tool = GitTool(workspace=str(workspace))
    if repository_exists:
        dirty = git_module.Repo(workspace).git.status("--porcelain").splitlines()
        if dirty:
            raise click.ClickException(
                "Current Git repository is dirty. Commit or stash changes first: "
                + ", ".join(dirty)
            )
    (workspace / "docs").mkdir(exist_ok=True)
    readme = workspace / "README.md"
    readme_created = not readme.exists()
    if not readme.exists():
        readme.write_text(f"# {name}\n\n{requirement}\n")

    if not repository_exists:
        git_tool.run(operation="init")

    repo = git_module.Repo(workspace)
    if not repo.head.is_valid() or readme_created:
        git_tool.run(operation="add", paths="README.md")
        git_tool.run(operation="commit", message="chore: initialize onep greenfield project")
    _exclude_onep_runtime(repo)

    project = Project(
        name=name,
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace),
    )
    project.requirement = requirement
    insert_project(project)

    from onep.greenfield.models import GreenfieldOptions
    options = GreenfieldOptions(
        max_rounds=max_rounds,
        max_repairs_per_slice=max_repairs_per_slice,
        max_cost=max_cost,
        test_commands=list(test_commands),
        deploy_mode=deploy_mode,
        non_interactive=non_interactive,
        verbose=verbose,
    )
    state = PipelineState(artifacts={"greenfield_options": options.to_dict()})
    save_state(workspace, state)

    console.print(Panel.fit(
        f"[bold green]Project '{name}' created![/bold green]\n"
        f"Workspace: {workspace}\n"
        f"Mode: Greenfield autonomous loop\n\n"
        + (f"Run [bold cyan]onep run {name}[/bold cyan] to start."
           if no_run else "Starting autonomous engineering loop..."),
        title="OnePTeam",
    ))

    if not no_run:
        from onep.orchestrator.runner import run_pipeline
        if not run_pipeline(name, options=options):
            raise click.ClickException(
                f"Run did not complete. Resume with: onep run {name}"
            )


def _resolve_workspace(current_dir: Path) -> tuple[Path, bool]:
    """Use the current Git root, or initialize directly in the current directory."""
    current_dir = current_dir.resolve()
    try:
        repo = git_module.Repo(current_dir, search_parent_directories=True)
    except (git_module.InvalidGitRepositoryError, git_module.NoSuchPathError):
        return current_dir, False
    if repo.bare or repo.working_tree_dir is None:
        raise click.ClickException("Current Git repository must have a working tree")
    return Path(repo.working_tree_dir).resolve(), True


def _exclude_onep_runtime(repo: git_module.Repo) -> None:
    exclude = Path(repo.git_dir) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    content = exclude.read_text() if exclude.exists() else ""
    if ".onep/" not in content.splitlines():
        separator = "" if not content or content.endswith("\n") else "\n"
        exclude.write_text(content + separator + ".onep/\n")


@click.command()
@click.argument("project_name", type=str)
@click.option("--stage", "-s", default=None, help="Legacy checkpoint hint")
def run_cmd(project_name: str, stage: str | None):
    """Run or resume the autonomous engineering loop."""
    from onep.orchestrator.runner import run_pipeline
    success = run_pipeline(project_name, start_from=stage)
    if success:
        console.print("[bold green]Pipeline completed![/bold green]")
    else:
        console.print("[yellow]Pipeline paused or failed. Check: onep status[/yellow]")


COMMANDS = [create_cmd, run_cmd]
