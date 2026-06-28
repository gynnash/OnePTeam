"""onep optimize: LLM-led Plan execution with external safety gates."""
from __future__ import annotations

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import click
import git
from rich.console import Console

from onep.config import load_config
from onep.llm.adapters import LLMAdapter
from onep.llm.cost import CostTracker, estimate_call_cost
from onep.llm.router import resolve_model
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.strategy.analyzer import parse_analysis_response
from onep.strategy.git_session import GitRunSession
from onep.strategy.models import StrategyItem, classify_impact
from onep.strategy.optimize_coordinator import OptimizeCoordinator
from onep.strategy.optimize_engine import OptimizeEngine
from onep.strategy.optimize_models import (
    FailureReason, PlanCandidate, PlanRecord, PlanStatus, RunRecord, RunStatus,
)
from onep.strategy.optimize_recorder import OptimizeRunRecorder
from onep.strategy.plan_scheduler import PlanScheduler
from onep.strategy.planner import generate_optimize_plan
from onep.memory.context import (
    MemoryContextBuilder, MemoryContextRequest, append_memory_context,
)
from onep.strategy.project_context import load_project_context
from onep.strategy.reviewer import ReviewAgent
from onep.strategy.scanner import (
    aggregate_chunk_results, aggregate_file_results, batch_files,
    build_content_batches, get_strategy_files, parse_scan_response, walk_files,
)
from onep.strategy.test_runner import PlanTestRunner

console = Console()


@click.command()
@click.argument("source", type=click.Path(path_type=Path))
@click.option("--max-rounds", type=click.IntRange(1), default=5)
@click.option("--auto-approve", default="low,medium",
              help="Impact levels to auto-execute (comma-separated)")
@click.option("--max-cost", type=click.FloatRange(min=0), default=0)
@click.option("--name", "-n", default=None)
@click.option("--test-command", "test_commands", multiple=True,
              help="External test gate command; may be repeated")
@click.option("--integration-test-command", "integration_commands", multiple=True,
              help="Integration test command; may be repeated")
def optimize_cmd(
    source: Path,
    max_rounds: int,
    auto_approve: str,
    max_cost: float,
    name: str | None,
    test_commands: tuple[str, ...],
    integration_commands: tuple[str, ...],
):
    """Analyze, plan, develop, test, review, and integrate improvements."""
    source_path = source.resolve()
    try:
        git.Repo(source_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as exc:
        raise click.ClickException("SOURCE must be a Git repository") from exc

    name = name or re.sub(r"[^\w]", "", source_path.name)[:20]
    name = name or f"optimize-{uuid.uuid4().hex[:6]}"
    config = load_config()
    if max_cost > 0:
        missing_pricing = []
        for stage in (
            "analyzer", "strategy_architect",
            "optimize_developer", "code_reviewer",
        ):
            model = resolve_model(stage)[0]
            prices = config.llm.pricing.get(model) or {}
            if not prices.get("input") or not prices.get("output"):
                missing_pricing.append(model)
        if missing_pricing:
            raise click.ClickException(
                "Missing pricing for budget enforcement: "
                + ", ".join(sorted(set(missing_pricing)))
            )
    init_db()
    workspace = (
        Path(os.path.expanduser(config.project.root_dir))
        / "projects" / name / "workspace"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    insert_project(Project(
        name=name, mode=ProjectMode.BROWNFIELD,
        workspace_path=str(workspace),
    ))

    run_id = f"{__import__('datetime').datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    run_dir = workspace / "optimize" / "runs" / run_id
    git_session = GitRunSession(source_path, run_dir, run_id)
    integration_branch = git_session.create_integration_branch()
    run = RunRecord(
        id=run_id,
        project_name=name,
        source_path=source_path,
        status=RunStatus.RUNNING,
        base_commit=git_session.base_commit,
        integration_branch=integration_branch,
        base_branch=git_session.base_branch,
        budget=max_cost,
    )
    recorder = OptimizeRunRecorder(run_dir, run)
    recorder.record_event("run_started", {
        "source": source_path, "max_rounds": max_rounds,
        "max_cost": max_cost,
    })
    tracker = CostTracker(max_cost)
    scheduler = PlanScheduler()
    fingerprint_registry: dict[str, PlanStatus] = {}
    auto_levels = {value.strip() for value in auto_approve.split(",") if value.strip()}
    commands = test_commands or ("pytest -q",)
    integration_commands = integration_commands or ("pytest -q",)
    context = load_project_context(workspace, str(source_path))

    try:
        for round_number in range(1, max_rounds + 1):
            console.print(f"\n[bold]=== Round {round_number}/{max_rounds} ===[/bold]")
            llm = LLMAdapter()
            analysis_source = git_session.integration_worktree
            items = _analyze(analysis_source, llm, tracker, name)
            candidates: list[tuple[PlanCandidate, str]] = []
            for index, item in enumerate(items, 1):
                item.impact = classify_impact(
                    item.title, item.summary, item.tags, item.impact
                )
                if item.impact not in auto_levels:
                    skipped = _candidate(item, commands)
                    plan_record = PlanRecord(skipped, status=PlanStatus.SKIPPED)
                    run.plans.append(plan_record)
                    recorder.save_plan(plan_record, "")
                    continue
                if max_cost > 0 and not tracker.can_continue():
                    recorder.record_event("budget_exhausted", {
                        "round": round_number, "spent": tracker.spent,
                    })
                    break
                plan_memory = _memory_context(
                    "strategy_architect", name, item.title, item.id
                )
                reservation = _reservation_for(
                    "strategy_architect",
                    item.title + item.summary + plan_memory,
                )
                if (
                    reservation is None and max_cost > 0
                    or reservation is not None
                    and not tracker.reserve(reservation)
                ):
                    recorder.record_event("budget_exhausted", {
                        "round": round_number,
                        "stage": "strategy_architect",
                    })
                    break
                try:
                    generated = generate_optimize_plan(
                        item, workspace, llm_adapter=llm, plan_index=index,
                        memory_context=plan_memory,
                    )
                except Exception as exc:
                    failed_candidate = _candidate(item, commands)
                    failed_candidate.discovery_index = index
                    failed = PlanRecord(failed_candidate)
                    failed.fail(FailureReason.PLAN_GENERATION_FAILED, str(exc))
                    recorder.save_plan(failed, "")
                    run.plans.append(failed)
                    continue
                finally:
                    tracker.release(reservation or 0.0)
                    _record_usage(tracker, llm, "strategy_architect")
                candidate = _candidate(item, commands, generated)
                candidate.discovery_index = index
                candidates.append((candidate, generated.plan_markdown))

            _resolve_dependencies([candidate for candidate, _ in candidates])
            discovered = [candidate for candidate, _ in candidates]
            for candidate in discovered:
                candidate.fingerprint = (
                    candidate.fingerprint or scheduler.fingerprint(candidate)
                )
                if fingerprint_registry.get(candidate.fingerprint) == PlanStatus.INTEGRATED:
                    recorder.record_event("regression_detected", {
                        "item_id": candidate.id,
                        "fingerprint": candidate.fingerprint,
                    })
            fresh = scheduler.new_candidates(
                discovered, set(fingerprint_registry)
            )
            if not fresh:
                recorder.record_event("converged", {"round": round_number})
                break
            texts = {candidate.id: text for candidate, text in candidates}
            terminal_by_id = {
                plan.candidate.id: plan.status for plan in recorder.run.plans
            }
            executable = []
            for candidate in fresh:
                failed_dependencies = [
                    dependency for dependency in candidate.dependencies
                    if terminal_by_id.get(dependency) in {
                        PlanStatus.FAILED, PlanStatus.ROLLED_BACK,
                        PlanStatus.SKIPPED,
                    }
                ]
                if failed_dependencies:
                    skipped = PlanRecord(candidate)
                    skipped.failure_reason = FailureReason.DEPENDENCY_FAILED
                    skipped.failure_detail = ", ".join(failed_dependencies)
                    skipped.transition_to(PlanStatus.SKIPPED)
                    recorder.save_plan(skipped, texts.get(candidate.id, ""))
                    continue
                executable.append(candidate)
            satisfied = {
                plan.candidate.id for plan in recorder.run.plans
                if plan.status == PlanStatus.INTEGRATED
            }
            try:
                groups = scheduler.groups(executable, satisfied)
            except ValueError as exc:
                for candidate in executable:
                    failed = PlanRecord(candidate)
                    failed.fail(FailureReason.INVALID_PLAN_METADATA, str(exc))
                    recorder.save_plan(failed, texts.get(candidate.id, ""))
                break
            for group_index, group in enumerate(groups, 1):
                current_status = {
                    plan.candidate.id: plan.status
                    for plan in recorder.run.plans
                }
                runnable_group = []
                for candidate in group:
                    failed_dependencies = [
                        dependency for dependency in candidate.dependencies
                        if current_status.get(dependency) in {
                            PlanStatus.FAILED,
                            PlanStatus.ROLLED_BACK,
                            PlanStatus.SKIPPED,
                        }
                    ]
                    if failed_dependencies:
                        skipped = PlanRecord(candidate)
                        skipped.failure_reason = FailureReason.DEPENDENCY_FAILED
                        skipped.failure_detail = ", ".join(failed_dependencies)
                        skipped.transition_to(PlanStatus.SKIPPED)
                        recorder.save_plan(skipped, texts[candidate.id])
                        fingerprint_registry[candidate.fingerprint] = skipped.status
                    else:
                        runnable_group.append(candidate)
                group = runnable_group
                if not group:
                    continue
                recorder.record_event("group_started", {
                    "round": round_number,
                    "group": group_index,
                    "plans": [candidate.id for candidate in group],
                })
                sessions = git_session.create_plan_group(group)
                branch_failed = []
                for candidate in group:
                    if candidate.id not in sessions:
                        failed = PlanRecord(candidate)
                        failed.fail(
                            FailureReason.BRANCH_CREATE_FAILED,
                            git_session.last_group_errors.get(
                                candidate.id, "branch creation failed"
                            ),
                        )
                        recorder.save_plan(failed, texts[candidate.id])
                        fingerprint_registry[candidate.fingerprint] = failed.status
                        branch_failed.append(candidate.id)
                group = [
                    candidate for candidate in group
                    if candidate.id not in branch_failed
                ]
                if not group:
                    continue

                def execute(candidate):
                    plan_llm = LLMAdapter()
                    memory = _memory_context(
                        "optimize_developer", name,
                        f"{candidate.title} {candidate.summary}", candidate.id,
                    )
                    coordinator = OptimizeCoordinator(
                        OptimizeEngine(),
                        PlanTestRunner(config.pipeline.test_timeout),
                        ReviewAgent(plan_llm),
                        git_session,
                        llm=plan_llm,
                        recorder=recorder,
                        cost_tracker=tracker,
                        max_attempts=3,
                        project_context=append_memory_context(
                            context,
                            _memory_context(
                                "code_reviewer", name,
                                f"review {candidate.title}", candidate.id,
                            ),
                        ),
                        memory_context=memory,
                    )
                    return coordinator.develop_plan(
                        candidate, texts[candidate.id], sessions[candidate.id]
                    )

                with ThreadPoolExecutor(max_workers=len(group)) as executor:
                    futures = {
                        executor.submit(execute, candidate): candidate
                        for candidate in group
                    }
                    results = []
                    for future in as_completed(futures):
                        candidate = futures[future]
                        try:
                            results.append(future.result())
                        except Exception as exc:
                            failed = PlanRecord(candidate)
                            failed.fail(FailureReason.DEVELOPER_FAILED, str(exc))
                            results.append(failed)
                by_id = {result.candidate.id: result for result in results}
                integration_coordinator = OptimizeCoordinator(
                    OptimizeEngine(),
                    PlanTestRunner(config.pipeline.test_timeout),
                    ReviewAgent(LLMAdapter()),
                    git_session,
                    recorder=recorder,
                )
                for candidate in scheduler.integration_order(group):
                    result = by_id[candidate.id]
                    if result.status == PlanStatus.COMMITTED:
                        result = integration_coordinator.integrate_plan(
                            result, sessions[candidate.id],
                            list(integration_commands),
                        )
                    candidate = result.candidate
                    run.plans = [
                        plan for plan in run.plans
                        if plan.candidate.id != candidate.id
                    ] + [result]
                    recorder.save_plan(result, texts[candidate.id])
                    fingerprint_registry[candidate.fingerprint] = result.status
                _flush_cost(recorder, tracker)
            if not any(
                plan.status == PlanStatus.INTEGRATED
                for plan in run.plans
            ):
                break

        run = recorder.run
        run.total_cost = tracker.spent
        run.spent = tracker.spent
        run.remaining = tracker.remaining if max_cost > 0 else None
        run.cost_entries = [entry.to_dict() for entry in tracker.entries]
        run.integration_commit = getattr(
            git_session, "integration_commit", ""
        ) or git.Repo(
            git_session.integration_worktree
        ).head.commit.hexsha
        failures = [
            plan for plan in run.plans
            if plan.status in {PlanStatus.FAILED, PlanStatus.ROLLED_BACK}
        ]
        run.status = RunStatus.PARTIAL if failures else RunStatus.COMPLETED
        run.ended_at = datetime.now(timezone.utc).isoformat()
        run.status_counts = {
            status.value: sum(plan.status == status for plan in run.plans)
            for status in PlanStatus
        }
        recorder.save_state()
        report = _render_run_report(run)
        recorder.save_report(report)
        recorder.record_event("run_finished", {
            "status": run.status.value,
            "successful": sum(
                plan.status == PlanStatus.INTEGRATED for plan in run.plans
            ),
            "failed": len(failures),
        })
        console.print(report)
        console.print(f"[dim]Run records: {run_dir}[/dim]")
    except (KeyboardInterrupt, click.Abort) as exc:
        run = recorder.run
        run.status = RunStatus.CANCELLED
        run.failure_reason = FailureReason.CANCELLED
        run.failure_detail = "Optimize cancelled"
        run.ended_at = datetime.now(timezone.utc).isoformat()
        recorder.save_state()
        recorder.record_event("run_cancelled", {})
        raise click.ClickException("Optimize cancelled") from exc
    except Exception as exc:
        run = recorder.run
        run.status = RunStatus.FAILED
        run.failure_reason = FailureReason.INTERNAL_ERROR
        run.failure_detail = str(exc)
        run.ended_at = datetime.now(timezone.utc).isoformat()
        run.spent = tracker.spent
        run.cost_entries = [entry.to_dict() for entry in tracker.entries]
        recorder.save_state()
        recorder.record_event("run_failed", {
            "error_type": type(exc).__name__, "message": str(exc),
        })
        raise click.ClickException(
            f"Optimize failed: {type(exc).__name__}: {exc}. "
            f"Run records: {run_dir}"
        ) from exc
    finally:
        try:
            git_session.cleanup()
            recorder.record_event("run_cleanup_completed", {})
        except Exception as cleanup_exc:
            cleanup_run = recorder.run
            if cleanup_run.status == RunStatus.COMPLETED:
                cleanup_run.status = RunStatus.PARTIAL
            cleanup_run.failure_reason = FailureReason.ROLLBACK_FAILED
            cleanup_run.failure_detail = str(cleanup_exc)
            cleanup_run.artifacts["cleanup_error"] = str(cleanup_exc)
            recorder.save_state()
            recorder.record_event("run_cleanup_failed", {
                "error": str(cleanup_exc),
            })
            console.print(f"[yellow]Cleanup failed: {cleanup_exc}[/yellow]")


def _candidate(item: StrategyItem, commands: tuple[str, ...], generated=None) -> PlanCandidate:
    location = item.file_location.split(":", 1)[0].strip()
    expected = set(generated.expected_files if generated else item.expected_files)
    if location and location != "N/A":
        expected.add(location)
    return PlanCandidate(
        id=item.id,
        title=item.title,
        summary=item.summary,
        tags=set(item.tags),
        impact=item.impact,
        files={Path(path) for path in expected},
        dependencies=set(generated.dependencies if generated else item.dependencies),
        test_commands=(
            generated.test_commands if generated and generated.test_commands
            else commands
        ),
        risk_flags=set(generated.risk_flags if generated else ()),
    )


def _analyze(
    source: Path,
    llm: LLMAdapter,
    tracker: CostTracker | None = None,
    project_name: str = "",
) -> list[StrategyItem]:
    from onep.orchestrator.brownfield import ANALYZE_PROMPT, SCAN_PROMPT_FULL

    scan_results = []
    for files in batch_files(walk_files(source)):
        content_batches = build_content_batches(source, files)
        entries = [
            entry for batch in content_batches for entry in batch.entries
        ]
        chunk_results = []
        for content in content_batches:
            try:
                response = _budgeted_invoke(
                    llm, tracker, "analyzer",
                    system_prompt="You are the analyzer agent.",
                    user_prompt=append_memory_context(
                        SCAN_PROMPT_FULL.format(file_block=content.render()),
                        _memory_context(
                            "analyzer", project_name,
                            "classify strategy files", "",
                        ) if project_name else "",
                    ),
                )
                parsed = parse_scan_response(response)
            except Exception:
                parsed = []
            chunk_results.extend(aggregate_chunk_results(
                list(content.entries), parsed
            ))
        scan_results.extend(aggregate_file_results(
            [entry.relative_path for entry in entries], chunk_results
        ))
    strategy_files = get_strategy_files(scan_results)
    if not strategy_files:
        return []
    response = _budgeted_invoke(
        llm, tracker, "strategy_architect",
        system_prompt="You are the strategy architect.",
        user_prompt=append_memory_context(
            ANALYZE_PROMPT.format(
                file_list="\n".join(f"- {path}" for path in strategy_files),
                source_root=str(source),
            ),
            _memory_context(
                "strategy_architect", project_name,
                "discover optimization opportunities", "",
            ) if project_name else "",
        ),
    )
    return parse_analysis_response(response)


def _budgeted_invoke(
    llm: LLMAdapter,
    tracker: CostTracker | None,
    stage: str,
    **kwargs,
) -> str:
    reservation = _reservation_for(
        stage, str(kwargs.get("user_prompt") or "")
    )
    if tracker and (
        reservation is None and tracker.budget > 0
        or reservation is not None and not tracker.reserve(reservation)
    ):
        raise RuntimeError(f"budget exhausted before {stage}")
    try:
        result = llm.invoke(stage_name=stage, **kwargs)
    finally:
        if tracker:
            tracker.release(reservation or 0.0)
    if tracker:
        _record_usage(tracker, llm, stage)
    return result


def _reservation_for(stage: str, prompt: str) -> float | None:
    config = load_config()
    return estimate_call_cost(
        resolve_model(stage)[0],
        prompt,
        getattr(config.pipeline, "stage_output_tokens", {}).get(stage, 4096),
    )


def _record_usage(
    tracker: CostTracker, llm: LLMAdapter, stage: str
) -> None:
    if not llm.last_usage.is_empty:
        tracker.record_usage(stage, resolve_model(stage)[0], llm.last_usage)


def _flush_cost(recorder, tracker: CostTracker) -> None:
    run = recorder.run
    run.spent = tracker.spent
    run.total_cost = tracker.spent
    run.remaining = tracker.remaining if tracker.budget > 0 else None
    run.cost_entries = [entry.to_dict() for entry in tracker.entries]
    recorder.save_state()


def _resolve_dependencies(candidates: list[PlanCandidate]) -> None:
    by_title = {candidate.title: candidate.id for candidate in candidates}
    ids = {candidate.id for candidate in candidates}
    for candidate in candidates:
        candidate.dependencies = {
            dependency if dependency in ids else by_title.get(dependency, dependency)
            for dependency in candidate.dependencies
        }


def _memory_context(
    stage: str, project_name: str, query: str, item_id: str = ""
) -> str:
    return MemoryContextBuilder().build(MemoryContextRequest(
        query=query,
        stage_name=stage,
        project_name=project_name,
        source_id=f"brownfield:{project_name}",
        local_top_k=6,
        global_top_k=3,
        local_min_score=0.15,
        global_min_score=0.45,
    ))


def _render_run_report(run: RunRecord) -> str:
    has_unknown_cost = any(
        entry.get("cost") is None for entry in run.cost_entries
    )
    cost_text = (
        f"${run.total_cost:.4f} + unknown"
        if has_unknown_cost else f"${run.total_cost:.4f}"
    )
    lines = [
        "# Optimize Report",
        f"- Run: {run.id}",
        f"- Status: {run.status.value}",
        f"- Cost: {cost_text}",
        f"- Base: {run.base_branch}@{run.base_commit}",
        f"- Integration: {run.integration_branch}@{run.integration_commit}",
        "",
    ]
    for plan in run.plans:
        reason = (
            f" ({plan.failure_reason.value}: {plan.failure_detail})"
            if plan.failure_reason else ""
        )
        lines.append(
            f"- [{plan.status.value}] {plan.candidate.title}{reason}; "
            f"branch={plan.branch or '-'}; commit={plan.commit_sha or '-'}; "
            f"attempts={len(plan.attempts)}"
        )
    return "\n".join(lines)


COMMANDS = [optimize_cmd]
