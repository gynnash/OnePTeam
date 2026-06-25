"""Pipeline runner — executes stages sequentially, handles state and checkpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from onep.config import load_config
from onep.persistence.database import (
    init_db, get_project, update_project,
    insert_stage_run, update_stage_run, list_projects,
)
from onep.persistence.models import (
    Project, PipelineState, StageRun, StageStatus, ProjectStatus,
)
from onep.persistence.state import load_state, save_state
from onep.tools.git import GitTool
from onep.orchestrator.greenfield import GREENFIELD_STAGES, STAGE_PROMPTS

console = Console()


def run_pipeline(project_name: str, start_from: Optional[str] = None) -> bool:
    """Execute the Greenfield pipeline. Returns True on success."""
    config = load_config()
    init_db()

    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return False

    workspace = Path(project.workspace_path)
    state = load_state(workspace)
    git = GitTool(workspace=workspace)

    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)

    approval_required_stages = {"pm", "architect"}

    for stage in GREENFIELD_STAGES:
        stage_name = stage["name"]

        if stage_name in state.stages_completed:
            continue

        if start_from and stage_name != start_from:
            continue
        start_from = None

        console.print(f"\n[bold cyan]▶ Stage: {stage_name} ({stage['agent']})[/bold cyan]")

        stage_run = StageRun(
            project_id=project.id,
            stage_name=stage_name,
            agent_name=stage["agent"],
        )
        stage_run.start()
        insert_stage_run(stage_run)

        project.current_stage = stage_name
        project.touch()
        update_project(project)
        state.current_stage = stage_name
        save_state(workspace, state)

        # Build prompt
        prd_content = ""
        prd_path = workspace / "docs" / "PRD.md"
        if prd_path.exists():
            prd_content = prd_path.read_text()

        prompt_template = STAGE_PROMPTS[stage_name]
        requirement = getattr(project, 'requirement', '')
        user_prompt = prompt_template.format(
            requirement=requirement,
            prd_content=prd_content,
            workspace=str(workspace),
        )

        system_prompt = (
            "你是一个软件开发团队的成员。请按照指令完成当前阶段的工作。"
            "直接输出结果，保存到指定文件，不需要额外解释。"
        )

        try:
            console.print(f"[dim]Agent: {stage['agent']} working...[/dim]")
            console.print(f"[dim]Prompt length: {len(user_prompt)} chars[/dim]")
            # In MVP, we simulate the agent's work by displaying the prompt
            # Real LLM invocation: from onep.llm.adapters import get_llm; get_llm().invoke(...)
            console.print("[yellow]LLM invocation skipped (MVP — requires API keys).[/yellow]")
            console.print(f"[dim]Agent would process: {stage['description']}[/dim]")

        except Exception as e:
            console.print(f"[red]Stage failed: {e}[/red]")
            stage_run.fail(str(e))
            update_stage_run(stage_run)
            project.status = ProjectStatus.FAILED
            project.touch()
            update_project(project)
            return False

        stage_run.complete(output_files=_detect_output_files(workspace, stage_name))
        update_stage_run(stage_run)

        if _has_uncommitted_changes(git):
            git.add(["."])
            git.commit(f"feat: {stage_name} stage completed — {stage['description']}")

        state.stages_completed.append(stage_name)
        state.current_stage = ""
        save_state(workspace, state)

        if stage_name in approval_required_stages and not config.pipeline.auto_approve:
            state.pending_approval = True
            save_state(workspace, state)
            console.print(f"[yellow]⏸ Approval required for stage: {stage_name}[/yellow]")
            console.print(f"  Run: [bold cyan]onep approve {project_name}[/bold cyan] to continue")
            project.status = ProjectStatus.PAUSED
            project.touch()
            update_project(project)
            return False

        state.pending_approval = False
        save_state(workspace, state)

    project.status = ProjectStatus.COMPLETED
    project.touch()
    update_project(project)

    console.print(f"\n[bold green]🎉 Project '{project_name}' completed successfully![/bold green]")
    return True


def _detect_output_files(workspace: Path, stage_name: str) -> list[str]:
    """Detect which files were created/modified by a stage."""
    stage_outputs = {
        "pm": ["docs/PRD.md"],
        "designer": ["docs/DESIGN.md"],
        "architect": ["docs/ARCHITECTURE.md"],
        "developer": ["backend/", "frontend/", "docker-compose.yml", "Dockerfile"],
        "tester": ["docs/TEST_REPORT.md"],
        "devops": ["docs/DEPLOY_LOG.md"],
    }
    expected = stage_outputs.get(stage_name, [])
    return [p for p in expected if (workspace / p).exists()]


def _has_uncommitted_changes(git: GitTool) -> bool:
    """Check if workspace has uncommitted changes."""
    status = git.status()
    return "nothing to commit" not in status and "nothing added to commit" not in status
