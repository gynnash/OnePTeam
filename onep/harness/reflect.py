# onep/harness/reflect.py
"""REFLECT stage and STOP evaluation of the Product Loop."""
from __future__ import annotations

from typing import Any

from onep.greenfield.models import AcceptanceContract, GreenfieldRun
from onep.harness.discover import _json_object
from onep.harness.models import (
    HarnessRun,
    ImprovementCandidate,
    QualitySnapshot,
    StopDecision,
    StopReason,
)


REFLECTOR_SYSTEM = (
    "You are the Product Reflector for an autonomous development harness. "
    "Return JSON only."
)

REFLECTOR_PROMPT = """Evaluate the product state after build round {iteration}.

Acceptance summary:
{acceptance}

Review findings:
{findings}

Deterministic snapshot: acceptance_pass_rate={acceptance_rate},
test_pass_rate={test_rate}

Return JSON only:
{{"goal_coverage": 0.0, "architecture_quality": 0.0, "blocker_count": 0,
"risks": ["..."], "quality_score": 0.0}}
All floats are 0-1. blocker_count is a non-negative integer."""


class ReflectStage:
    """Deterministic snapshot + optional LLM-scored dimensions. The quality
    score is anchored: 70% deterministic data, 30% LLM judgment."""

    def run(
        self,
        run: GreenfieldRun,
        contract: AcceptanceContract,
        hard_gates_passed: bool,
        iteration: int,
        llm=None,
        review_findings: list[str] | None = None,
        tracker=None,
        track=None,
    ) -> QualitySnapshot:
        required = [
            item for item in contract.items if item.priority in {"P0", "P1"}
        ] or list(contract.items)
        passed = sum(1 for item in required if item.status == "passed")
        acceptance_rate = passed / len(required) if required else 0.0
        test_rate = 1.0 if hard_gates_passed else 0.0
        coverage = 1.0 if hard_gates_passed else acceptance_rate
        deterministic_score = 0.7 * acceptance_rate + 0.3 * test_rate
        snapshot = QualitySnapshot(
            iteration=iteration,
            acceptance_pass_rate=round(acceptance_rate, 4),
            test_pass_rate=test_rate,
            goal_coverage=round(coverage, 4),
            quality_score=round(deterministic_score, 4),
            hard_gates_passed=hard_gates_passed,
        )
        if llm is None:
            return snapshot
        findings = "\n".join(review_findings or []) or "(none)"
        output = llm.invoke(
            system_prompt=REFLECTOR_SYSTEM,
            user_prompt=REFLECTOR_PROMPT.format(
                iteration=iteration,
                acceptance="\n".join(
                    f"- {item.id} [{item.priority}] {item.behavior} "
                    f"({item.status})" for item in contract.items
                ) or "(none)",
                findings=findings,
                acceptance_rate=snapshot.acceptance_pass_rate,
                test_rate=snapshot.test_pass_rate,
            ),
            stage_name="harness_reflector",
        )
        if track is not None and tracker is not None:
            track(tracker, "harness_reflector")
        data = _json_object(output or "")

        def _bounded(key: str, default: float) -> float:
            try:
                value = float(data.get(key))
            except (TypeError, ValueError):
                return default
            return min(1.0, max(0.0, value))

        llm_quality = _bounded("quality_score", deterministic_score)
        llm_coverage = _bounded("goal_coverage", snapshot.goal_coverage)
        snapshot.goal_coverage = round(
            min(snapshot.goal_coverage, llm_coverage), 4
        )
        snapshot.architecture_quality = _bounded(
            "architecture_quality", 0.0
        )
        try:
            snapshot.blocker_count = max(
                0, int(data.get("blocker_count") or 0)
            )
        except (TypeError, ValueError):
            snapshot.blocker_count = 0
        raw_risks = data.get("risks") or []
        snapshot.risks = [
            str(risk) for risk in raw_risks if isinstance(risk, str)
        ][:10]
        snapshot.quality_score = round(
            0.7 * deterministic_score + 0.3 * llm_quality, 4
        )
        return snapshot


def evaluate_stop(
    run: HarnessRun,
    snapshot: QualitySnapshot,
    backlog: list[ImprovementCandidate],
    scored: list[ImprovementCandidate] | None = None,
    diminishing_delta: float = 0.02,
    diminishing_rounds: int = 2,
) -> StopDecision:
    """Soft gates per spec §5.3 (hard gates are enforced by the engine).

    Order: MAX_ITERATION, BUDGET_EXHAUSTED, empty-backlog (GOALS_SATISFIED
    when DISCOVER produced nothing / NO_HIGH_VALUE_WORK when candidates
    were scored but none cleared the backlog threshold), DIMINISHING_RETURNS.
    """
    evidence: dict[str, Any] = {
        "iteration": run.iteration,
        "quality_score": snapshot.quality_score,
    }
    if run.quality_history:
        evidence["quality_curve"] = [
            round(history.quality_score, 4)
            for history in run.quality_history[-3:]
        ]
    if run.iteration >= run.options.max_rounds:
        return StopDecision(True, StopReason.MAX_ITERATION, evidence)
    if run.options.max_cost > 0 and run.spent >= run.options.max_cost:
        return StopDecision(True, StopReason.BUDGET_EXHAUSTED, evidence)
    if not backlog:
        if scored:
            top_score = max(
                (candidate.score or 0.0 for candidate in scored),
                default=0.0,
            )
            evidence.update({
                "top_score": top_score,
                "scored_count": len(scored),
                "score_distribution": {
                    candidate.id: candidate.score for candidate in scored
                },
            })
            return StopDecision(
                True, StopReason.NO_HIGH_VALUE_WORK, evidence
            )
        return StopDecision(True, StopReason.GOALS_SATISFIED, evidence)
    deltas = _consecutive_deltas(run.quality_history, diminishing_rounds)
    if deltas is not None and all(
        delta < diminishing_delta for delta in deltas
    ):
        evidence["deltas"] = deltas
        return StopDecision(True, StopReason.DIMINISHING_RETURNS, evidence)
    return StopDecision(False, None, evidence)


def _consecutive_deltas(
    history: list[QualitySnapshot], rounds: int = 2
) -> list[float] | None:
    """Absolute quality deltas between the last rounds+1 snapshots, or None
    when the history is too short."""
    tail = history[-(rounds + 1):]
    if len(tail) < rounds + 1:
        return None
    return [
        round(
            abs(tail[index + 1].quality_score - tail[index].quality_score), 4
        )
        for index in range(len(tail) - 1)
    ]
