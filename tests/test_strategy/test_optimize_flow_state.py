import pytest

from onep.strategy.optimize_flow import OptimizeFlow, OptimizeFlowStage
from onep.strategy.optimize_models import PlanCandidate, PlanStatus
from onep.strategy.plan_scheduler import PlanScheduler
from pathlib import Path


def test_optimize_flow_allows_repeated_develop_integrate_groups():
    emitted = []
    flow = OptimizeFlow(lambda kind, payload: emitted.append((kind, payload)))
    flow.start_round(1)
    flow.transition(OptimizeFlowStage.PLAN)
    flow.transition(OptimizeFlowStage.SCHEDULE)
    flow.transition(OptimizeFlowStage.DEVELOP)
    flow.transition(OptimizeFlowStage.INTEGRATE)
    flow.transition(OptimizeFlowStage.DEVELOP)
    flow.transition(OptimizeFlowStage.INTEGRATE)
    flow.transition(OptimizeFlowStage.VERIFY)
    flow.finish()
    assert flow.stage == OptimizeFlowStage.FINISHED
    assert emitted[0][1]["stage"] == "discover"


def test_optimize_flow_rejects_skipping_deterministic_gates():
    flow = OptimizeFlow()
    flow.start_round(1)
    with pytest.raises(ValueError, match="Illegal optimize flow transition"):
        flow.transition(OptimizeFlowStage.INTEGRATE)


def test_optimize_flow_converges_from_discovery():
    flow = OptimizeFlow()
    flow.start_round(1)
    flow.converge("no_repository_changes")
    flow.finish()
    assert flow.stage == OptimizeFlowStage.FINISHED


def test_optimize_flow_classifies_rediscovered_integrated_issue_as_regression():
    scheduler = PlanScheduler()
    candidate = PlanCandidate(
        id="new-id", title="Cache issue", files={Path("cache.py")}
    )
    fingerprint = scheduler.fingerprint(candidate)
    fresh, regressions = OptimizeFlow().classify_discoveries(
        [candidate], {fingerprint: PlanStatus.INTEGRATED}, scheduler
    )
    assert fresh == []
    assert regressions == [candidate]
