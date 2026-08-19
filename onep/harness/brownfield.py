"""Brownfield routing for the unified harness.

UNDERSTAND scans the existing codebase into PlanCandidates; BUILD develops
each candidate through the hardened OptimizeCoordinator kernel. The Product
Loop (REFLECT -> DISCOVER -> PRIORITIZE -> STOP) is shared with greenfield.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from onep.harness.models import CandidateAdapter, WorkItem
from onep.strategy.analyze_pipeline import analyze_source, candidate_from_item
from onep.strategy.git_session import GitRunSession
from onep.strategy.models import StrategyItem, classify_impact
from onep.strategy.optimize_coordinator import OptimizeCoordinator
from onep.strategy.optimize_engine import OptimizeEngine
from onep.strategy.optimize_models import PlanCandidate, PlanStatus
from onep.strategy.planner import generate_optimize_plan
from onep.strategy.reviewer import ReviewAgent
from onep.strategy.test_runner import PlanTestRunner


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
        items = self.analyzer(workspace, self.llm, tracker, project_name)
        candidates: list[PlanCandidate] = []
        plans: dict[str, str] = {}
        for index, item in enumerate(items, 1):
            item.impact = classify_impact(
                item.title, item.summary, item.tags, item.impact
            )
            generated = self.planner(item, workspace, self.llm, plan_index=index)
            candidate = candidate_from_item(item, test_commands, generated)
            candidates.append(candidate)
            plans[candidate.id] = generated.plan_markdown
        return candidates, plans


class BrownfieldBuildStage:
    """BUILD for candidate WorkItems: the hardened optimize kernel.

    One worktree per item; develop -> integrate through the existing
    OptimizeCoordinator (engine tool loop, scope gate, real tests,
    read-only review, repair). Sequential — no parallel groups (spec §11).
    """

    def __init__(
        self,
        workspace: Path,
        run_dir: Path,
        run_id: str,
        llm,
        tracker=None,
        recorder=None,
        project_context: str = "",
        test_timeout: int = 300,
        session_factory: Callable[..., Any] | None = None,
        coordinator_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self.run_dir = run_dir
        self.run_id = run_id
        self.llm = llm
        self.tracker = tracker
        self.recorder = recorder
        self.project_context = project_context
        self.test_timeout = test_timeout
        self.session_factory = session_factory or GitRunSession
        self.coordinator_factory = coordinator_factory or OptimizeCoordinator

    def build(
        self,
        items: list[WorkItem],
        plans: dict[str, str],
        integration_commands: list[str],
    ) -> dict:
        updated = list(items)
        records = []
        integration_passed = True
        if not updated:
            return {
                "items": updated,
                "records": records,
                "integration_passed": True,
            }
        git_session = self.session_factory(self.workspace, self.run_dir, self.run_id)
        git_session.create_integration_branch()
        for item in updated:
            if item.status != "pending":
                continue
            candidate = CandidateAdapter.to_plan_candidate(item)
            coordinator = self.coordinator_factory(
                OptimizeEngine(),
                PlanTestRunner(self.test_timeout),
                ReviewAgent(self.llm),
                git_session,
                llm=self.llm,
                recorder=self.recorder,
                cost_tracker=self.tracker,
                project_context=self.project_context,
            )
            session = git_session.create_plan_session(candidate.id, candidate.title)
            record = coordinator.develop_plan(
                candidate, plans.get(item.id, ""), session
            )
            if record.status == PlanStatus.COMMITTED:
                record = coordinator.integrate_plan(
                    record, session, list(integration_commands)
                )
            records.append(record)
            item.attempts = len(record.attempts)
            item.commit_sha = record.commit_sha or ""
            if record.status == PlanStatus.INTEGRATED:
                item.status = "completed"
            else:
                item.status = "failed"
                integration_passed = False
        return {
            "items": updated,
            "records": records,
            "integration_passed": integration_passed,
        }
