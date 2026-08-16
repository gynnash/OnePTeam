"""Brownfield routing for the unified harness.

UNDERSTAND scans the existing codebase into PlanCandidates; BUILD develops
each candidate through the hardened OptimizeCoordinator kernel. The Product
Loop (REFLECT -> DISCOVER -> PRIORITIZE -> STOP) is shared with greenfield.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from onep.strategy.analyze_pipeline import analyze_source, candidate_from_item
from onep.strategy.models import StrategyItem, classify_impact
from onep.strategy.optimize_models import PlanCandidate
from onep.strategy.planner import generate_optimize_plan


class BrownfieldUnderstandStage:
    """Scan the codebase, generate plans, and produce candidate WorkItems."""

    def __init__(
        self,
        llm,
        analyzer: Callable[..., list[StrategyItem]] | None = None,
        planner: Callable[..., Any] | None = None,
    ) -> None:
        self.llm = llm
        self.analyzer = analyzer or analyze_source
        self.planner = planner or generate_optimize_plan

    def run(
        self,
        workspace: Path,
        project_name: str,
        test_commands: tuple[str, ...],
        tracker=None,
    ) -> tuple[list[PlanCandidate], dict[str, str]]:
        items = self.analyzer(
            workspace, self.llm, tracker, project_name
        )
        candidates: list[PlanCandidate] = []
        plans: dict[str, str] = {}
        for index, item in enumerate(items, 1):
            item.impact = classify_impact(
                item.title, item.summary, item.tags, item.impact
            )
            generated = self.planner(
                item, workspace, self.llm, plan_index=index
            )
            candidate = candidate_from_item(item, test_commands, generated)
            candidates.append(candidate)
            plans[candidate.id] = generated.plan_markdown
        return candidates, plans
