# onep/harness/reflect.py
"""REFLECT stage and STOP evaluation of the Product Loop."""
from __future__ import annotations

from onep.greenfield.models import AcceptanceContract, GreenfieldRun
from onep.harness.models import (
    HarnessRun,
    ImprovementCandidate,
    QualitySnapshot,
    StopDecision,
    StopReason,
)


class ReflectStage:
    """Produce a deterministic quality snapshot. P2 adds LLM-scored
    dimensions and the marginal-utility curve."""

    def run(
        self,
        run: GreenfieldRun,
        contract: AcceptanceContract,
        hard_gates_passed: bool,
        iteration: int,
    ) -> QualitySnapshot:
        required = [
            item for item in contract.items if item.priority in {"P0", "P1"}
        ] or list(contract.items)
        passed = sum(1 for item in required if item.status == "passed")
        acceptance_rate = passed / len(required) if required else 0.0
        test_rate = 1.0 if hard_gates_passed else 0.0
        coverage = 1.0 if hard_gates_passed else acceptance_rate
        score = 0.7 * acceptance_rate + 0.3 * test_rate
        return QualitySnapshot(
            iteration=iteration,
            acceptance_pass_rate=round(acceptance_rate, 4),
            test_pass_rate=test_rate,
            goal_coverage=round(coverage, 4),
            quality_score=round(score, 4),
            hard_gates_passed=hard_gates_passed,
        )


def evaluate_stop(
    run: HarnessRun,
    snapshot: QualitySnapshot,
    backlog: list[ImprovementCandidate],
) -> StopDecision:
    """STOP evaluation v1. DIMINISHING_RETURNS and the opportunity-score
    threshold arrive in P2."""
    evidence = {
        "iteration": run.iteration,
        "quality_score": snapshot.quality_score,
    }
    if run.iteration >= run.options.max_rounds:
        return StopDecision(True, StopReason.MAX_ITERATION, evidence)
    if run.options.max_cost > 0 and run.spent >= run.options.max_cost:
        return StopDecision(True, StopReason.BUDGET_EXHAUSTED, evidence)
    if not backlog:
        return StopDecision(True, StopReason.GOALS_SATISFIED, evidence)
    return StopDecision(False, None, evidence)
