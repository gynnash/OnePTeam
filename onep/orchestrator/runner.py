"""Pipeline runner — executes stages sequentially, calls LLMs, handles checkpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from onep.config import load_config
from onep.agents.registry import get_agent
from onep.persistence.database import (
    init_db, update_project, insert_stage_run, update_stage_run, list_projects,
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
    git = GitTool(workspace=str(workspace))

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

        # ----- stage run tracking -----
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

        # ----- build prompt -----
        prd_content = ""
        prd_path = workspace / "docs" / "PRD.md"
        if prd_path.exists():
            prd_content = prd_path.read_text()

        design_content = ""
        design_path = workspace / "docs" / "DESIGN.md"
        if design_path.exists():
            design_content = design_path.read_text()

        arch_content = ""
        arch_path = workspace / "docs" / "ARCHITECTURE.md"
        if arch_path.exists():
            arch_content = arch_path.read_text()

        user_prompt = STAGE_PROMPTS[stage_name].format(
            requirement=project.requirement,
            prd_content=prd_content,
            design_content=design_content,
            arch_content=arch_content,
            workspace=str(workspace),
        )

        system_prompt = _build_agent_system_prompt(stage["agent"], workspace=str(workspace))

        # ----- invoke LLM -----
        try:
            console.print(f"[dim]Agent {stage['agent']} working...[/dim]")
            response = _invoke_agent(stage["agent"], system_prompt, user_prompt)

            if response is None:
                console.print(
                    "[yellow]LLM 不可用（请配置 API 密钥），Stage 跳过。"
                    "Agent 会输出到聊天窗口，由用户手动执行。[/yellow]"
                )
            else:
                console.print(f"[dim]Response received ({len(response)} chars)[/dim]")
                _save_agent_output(workspace, response, stage_name)

        except Exception as e:
            console.print(f"[red]Stage failed: {e}[/red]")
            stage_run.fail(str(e))
            update_stage_run(stage_run)
            project.status = ProjectStatus.FAILED
            project.touch()
            update_project(project)
            return False

        # ----- run subflows if applicable -----
        if stage_name == "developer":
            _run_code_review(workspace)
        elif stage_name == "tester":
            _run_test_retry(workspace)

        # ----- commit -----
        stage_run.complete(output_files=_detect_output_files(workspace, stage_name))
        update_stage_run(stage_run)

        if _has_uncommitted_changes(git):
            git.run(operation="add", paths=".")
            git.run(operation="commit", message=f"feat: {stage_name} stage completed — {stage['description']}")

        state.stages_completed.append(stage_name)
        state.current_stage = ""
        save_state(workspace, state)

        # ----- approval gate -----
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


def _build_agent_system_prompt(agent_name: str, workspace: str = "") -> str:
    """Build a system prompt from an agent's registered role, goal, and backstory."""
    agent = get_agent(agent_name, workspace=workspace)
    return (
        f"{agent.role}\n\n"
        f"目标: {agent.goal}\n\n"
        f"背景: {agent.backstory}\n\n"
        f"请按照指令完成当前阶段的工作。直接输出结果，保存到指定文件，不需要额外解释。"
    )


def _invoke_agent(agent_name: str, system_prompt: str, user_prompt: str) -> str | None:
    """Invoke LLM via the adapter. Returns None if unavailable."""
    try:
        from onep.llm.adapters import get_llm
        return get_llm().invoke(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stage_name=agent_name,
        )
    except Exception as e:
        console.print(f"[yellow]LLM 调用失败: {e}[/yellow]")
        return None


def _save_agent_output(workspace: Path, response: str, stage_name: str) -> None:
    """Extract file blocks from agent response and write them to workspace.

    Supports ```file:path ... ``` and ```path ... ``` blocks.
    """
    import re

    saved = 0
    # Pattern: ```optional-label:path\n content ```
    for match in re.finditer(r'```(?:[\w-]+:)?([\w./-]+)\n(.*?)```', response, re.DOTALL):
        filepath = match.group(1).strip()
        content = match.group(2).strip()
        full_path = workspace / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        saved += 1

    if saved == 0:
        # No file blocks found; save raw response as stage output
        output_file = workspace / "docs" / f"STAGE_{stage_name.upper()}_OUTPUT.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(response)
        console.print(f"[dim]Raw output saved to {output_file}[/dim]")
    else:
        console.print(f"[dim]{saved} file(s) saved from agent response[/dim]")


def _run_code_review(workspace: Path) -> None:
    """Run LangGraph code review subflow after developer stage."""
    try:
        from onep.subflows.code_review import run_code_review
        console.print("[dim]Running code review subflow...[/dim]")
        result = run_code_review(workspace)
        if result["status"] == "passed":
            console.print("[green]Code review: passed[/green]")
        else:
            console.print(f"[yellow]Code review: {result['status']} (iteration {result['iteration']})[/yellow]")
    except Exception as e:
        console.print(f"[dim]Code review skipped: {e}[/dim]")


def _run_test_retry(workspace: Path) -> None:
    """Run LangGraph test retry subflow after tester stage."""
    try:
        from onep.subflows.test_retry import run_test_loop
        console.print("[dim]Running test retry subflow...[/dim]")
        result = run_test_loop(workspace, test_command="pytest tests/ -v --tb=short")
        if result["passed"]:
            console.print("[green]Tests: all passing[/green]")
        else:
            console.print(f"[yellow]Tests: {result['status']} (iteration {result['iteration']})[/yellow]")
            console.print(f"[dim]{result['test_output'][:500]}[/dim]")
    except Exception as e:
        console.print(f"[dim]Test retry skipped: {e}[/dim]")


def _detect_output_files(workspace: Path, stage_name: str) -> list[str]:
    """Detect which files were created/modified by a stage."""
    stage_outputs = {
        "pm": ["docs/PRD.md", "docs/STAGE_PM_OUTPUT.md"],
        "designer": ["docs/DESIGN.md", "docs/STAGE_DESIGNER_OUTPUT.md"],
        "architect": ["docs/ARCHITECTURE.md", "docs/STAGE_ARCHITECT_OUTPUT.md"],
        "developer": ["backend/", "frontend/", "docker-compose.yml", "Dockerfile",
                       "docs/STAGE_DEVELOPER_OUTPUT.md"],
        "tester": ["docs/TEST_REPORT.md", "docs/STAGE_TESTER_OUTPUT.md"],
        "devops": ["docs/DEPLOY_LOG.md", "docs/STAGE_DEVOPS_OUTPUT.md"],
    }
    expected = stage_outputs.get(stage_name, [])
    return [p for p in expected if (workspace / p).exists()]


def _has_uncommitted_changes(git: GitTool) -> bool:
    """Check if workspace has uncommitted changes."""
    try:
        import git as gitpython
        repo = gitpython.Repo(str(git.workspace))
        return repo.is_dirty(untracked_files=True)
    except Exception:
        status = git.run(operation="status")
        return "nothing to commit" not in status and "nothing added to commit" not in status
