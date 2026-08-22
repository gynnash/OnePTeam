"""Reusable brownfield analysis pipeline: scan -> classify -> candidates.

Shared by the `onep optimize` CLI (budgeted) and the harness brownfield
UNDERSTAND stage (plain invoke). Extracted from onep/cli/optimize_cmd.py
so both entry points run the identical pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from onep.config import load_config
from onep.llm.cost import CostTracker, estimate_call_cost
from onep.llm.router import resolve_model
from onep.strategy.analyzer import parse_analysis_response
from onep.strategy.models import StrategyItem
from onep.strategy.optimize_models import PlanCandidate
from onep.strategy.scanner import (
    aggregate_chunk_results, aggregate_file_results, batch_files,
    build_content_batches, get_strategy_files, parse_scan_response,
    walk_files,
)


def reservation_for(stage: str, prompt: str) -> float | None:
    config = load_config()
    return estimate_call_cost(
        resolve_model(stage)[0],
        prompt,
        getattr(config.pipeline, "stage_output_tokens", {}).get(stage, 4096),
    )


def record_usage(tracker: CostTracker, llm, stage: str) -> None:
    if not llm.last_usage.is_empty:
        tracker.record_usage(stage, resolve_model(stage)[0], llm.last_usage)


def budgeted_invoke(
    llm,
    tracker: CostTracker | None,
    stage: str,
    on_usage: Callable[[CostTracker, Any, str], None] | None = None,
    **kwargs,
) -> str:
    reservation = reservation_for(stage, str(kwargs.get("user_prompt") or ""))
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
        (on_usage or record_usage)(tracker, llm, stage)
    return result


def analyze_source(
    source: Path,
    llm,
    tracker: CostTracker | None = None,
    project_name: str = "",
    source_files: list[Path] | None = None,
    goal: str = "",
    budgeted: Callable[..., str] | None = None,
    memory_context: Callable[[str, str, str, str], str] | None = None,
) -> list[StrategyItem]:
    from onep.memory.context import append_memory_context
    from onep.orchestrator.brownfield import ANALYZE_PROMPT, SCAN_PROMPT_FULL

    if budgeted is None:
        def invoke_without_budget_callback(**kwargs):
            return _plain_invoke(llm, tracker, **kwargs)

        budgeted = invoke_without_budget_callback

    def _memory(stage: str, query: str, item_id: str = "") -> str:
        if memory_context is None:
            return ""
        return memory_context(stage, project_name, query, item_id)

    scan_results = []
    for files in batch_files(source_files or walk_files(source)):
        content_batches = build_content_batches(source, files)
        entries = [
            entry for batch in content_batches for entry in batch.entries
        ]
        chunk_results = []
        for content in content_batches:
            try:
                response = budgeted(
                    stage_name="analyzer",
                    system_prompt="You are the analyzer agent.",
                    user_prompt=append_memory_context(
                        SCAN_PROMPT_FULL.format(file_block=content.render()),
                        _memory(
                            "analyzer", "classify strategy files"
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
    analysis_prompt = ANALYZE_PROMPT.format(
        file_list="\n".join(f"- {path}" for path in strategy_files),
        source_root=str(source),
    )
    if goal.strip():
        analysis_prompt += (
            "\n\nUser optimization goal:\n"
            f"{goal.strip()}\nPrioritize findings that advance this goal."
        )
    response = budgeted(
        stage_name="strategy_architect",
        system_prompt="You are the strategy architect.",
        user_prompt=append_memory_context(
            analysis_prompt,
            _memory(
                "strategy_architect", "discover optimization opportunities"
            ) if project_name else "",
        ),
    )
    return parse_analysis_response(response)


def _plain_invoke(llm, tracker: CostTracker | None, **kwargs) -> str:
    result = llm.invoke(**kwargs)
    if tracker is not None:
        record_usage(tracker, llm, str(kwargs.get("stage_name") or ""))
    return result


def candidate_from_item(
    item: StrategyItem,
    commands: tuple[str, ...],
    generated=None,
) -> PlanCandidate:
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
        test_commands=commands,
        focused_test_commands=(
            generated.test_commands if generated else ()
        ),
        risk_flags=set(generated.risk_flags if generated else ()),
    )
