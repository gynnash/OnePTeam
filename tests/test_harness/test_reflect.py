# tests/test_harness/test_reflect.py
from onep.greenfield.models import AcceptanceContract, AcceptanceItem, GreenfieldRun
from onep.harness.models import (
    HarnessRun,
    ImprovementCandidate,
    QualitySnapshot,
    StopReason,
)
from onep.harness.reflect import ReflectStage, evaluate_stop


def _contract(passed: int, total: int) -> AcceptanceContract:
    items = []
    for index in range(total):
        items.append(
            AcceptanceItem(
                id=f"REQ-{index}",
                priority="P0",
                behavior="works",
                status="passed" if index < passed else "pending",
            )
        )
    return AcceptanceContract(items)


def test_reflect_snapshot_full_pass():
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="r", workspace="/tmp"
    )
    snapshot = ReflectStage().run(run, _contract(2, 2), True, 1)
    assert snapshot.iteration == 1
    assert snapshot.hard_gates_passed is True
    assert snapshot.acceptance_pass_rate == 1.0
    assert snapshot.test_pass_rate == 1.0
    assert snapshot.goal_coverage == 1.0
    assert snapshot.quality_score == 1.0


def test_reflect_snapshot_partial_acceptance():
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="r", workspace="/tmp"
    )
    snapshot = ReflectStage().run(run, _contract(1, 4), False, 2)
    assert snapshot.acceptance_pass_rate == 0.25
    assert snapshot.test_pass_rate == 0.0
    assert snapshot.goal_coverage == 0.25
    assert round(snapshot.quality_score, 4) == round(0.7 * 0.25, 4)


def test_reflect_snapshot_empty_contract():
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="r", workspace="/tmp"
    )
    snapshot = ReflectStage().run(run, _contract(0, 0), True, 3)
    assert snapshot.acceptance_pass_rate == 0.0
    assert snapshot.hard_gates_passed is True


def _harness_run(**overrides):
    defaults = dict(
        id="h-1",
        project_name="demo",
        workspace="/tmp",
        mode="greenfield",
        original_goal="build value",
    )
    defaults.update(overrides)
    return HarnessRun(**defaults)


def _snapshot(score=1.0, hard=True):
    return QualitySnapshot(
        iteration=1,
        acceptance_pass_rate=1.0,
        test_pass_rate=1.0,
        goal_coverage=1.0,
        quality_score=score,
        hard_gates_passed=hard,
    )


def test_stop_when_no_backlog():
    decision = evaluate_stop(_harness_run(), _snapshot(), [])
    assert decision.stop is True
    assert decision.reason is StopReason.GOALS_SATISFIED


def test_stop_on_max_iteration():
    run = _harness_run(iteration=5)
    run.options.max_rounds = 5
    decision = evaluate_stop(
        run, _snapshot(), [ImprovementCandidate(id="I-1", title="T", description="d")]
    )
    assert decision.stop is True
    assert decision.reason is StopReason.MAX_ITERATION
    assert decision.evidence["iteration"] == 5


def test_stop_on_budget_exhausted():
    run = _harness_run(spent=3.0)
    run.options.max_cost = 2.0
    decision = evaluate_stop(
        run, _snapshot(), [ImprovementCandidate(id="I-1", title="T", description="d")]
    )
    assert decision.stop is True
    assert decision.reason is StopReason.BUDGET_EXHAUSTED


def test_continue_when_backlog_and_budget_available():
    run = _harness_run(iteration=1)
    run.options.max_rounds = 100
    decision = evaluate_stop(
        run, _snapshot(), [ImprovementCandidate(id="I-1", title="T", description="d")]
    )
    assert decision.stop is False
    assert decision.reason is None


class ReflectorLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        return self.payload


REFLECTOR_PAYLOAD = (
    '{"goal_coverage": 0.9, "architecture_quality": 0.8, '
    '"blocker_count": 1, "risks": ["slow startup"], '
    '"quality_score": 0.85}'
)


def test_reflect_with_llm_anchors_quality_score():
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="r", workspace="/tmp"
    )
    llm = ReflectorLLM(REFLECTOR_PAYLOAD)
    snapshot = ReflectStage().run(
        run,
        _contract(2, 2),
        True,
        1,
        llm=llm,
    )
    deterministic = 1.0  # 0.7 * 1.0 acceptance + 0.3 * 1.0 tests
    assert snapshot.quality_score == round(0.7 * deterministic + 0.3 * 0.85, 4)
    assert snapshot.goal_coverage == 0.9
    assert snapshot.architecture_quality == 0.8
    assert snapshot.blocker_count == 1
    assert snapshot.risks == ["slow startup"]
    assert llm.calls == ["harness_reflector"]


def test_reflect_with_llm_garbage_falls_back_to_deterministic():
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="r", workspace="/tmp"
    )
    llm = ReflectorLLM("not json")
    snapshot = ReflectStage().run(run, _contract(2, 2), True, 1, llm=llm)
    assert snapshot.quality_score == 1.0
    assert snapshot.architecture_quality == 0.0
    assert snapshot.blocker_count == 0
    assert snapshot.risks == []


def test_stop_no_high_value_work_with_scored_candidates():
    run = _harness_run()
    scored = [
        ImprovementCandidate(id="I-1", title="T1", score=0.6),
        ImprovementCandidate(id="I-2", title="T2", score=0.3),
    ]
    decision = evaluate_stop(run, _snapshot(), [], scored=scored)
    assert decision.stop is True
    assert decision.reason is StopReason.NO_HIGH_VALUE_WORK
    assert decision.evidence["top_score"] == 0.6
    assert decision.evidence["scored_count"] == 2


def test_high_value_candidate_with_missing_plan_does_not_stop():
    run = _harness_run()
    scored = [ImprovementCandidate(id="I-1", title="T1", score=0.9)]
    decision = evaluate_stop(run, _snapshot(), [], scored=scored)
    assert decision.stop is False
    assert decision.evidence["planning_blocked"] is True


def test_stop_diminishing_returns_after_two_flat_rounds():
    run = _harness_run(iteration=3)
    run.quality_history = [
        _snapshot(score=0.90),
        _snapshot(score=0.91),
        _snapshot(score=0.91),
    ]
    decision = evaluate_stop(
        run,
        _snapshot(score=0.91),
        [ImprovementCandidate(id="I-1", title="T", score=0.9)],
    )
    assert decision.stop is True
    assert decision.reason is StopReason.DIMINISHING_RETURNS
    assert "deltas" in decision.evidence


def test_continue_when_deltas_are_large():
    run = _harness_run(iteration=3)
    run.quality_history = [
        _snapshot(score=0.70),
        _snapshot(score=0.85),
        _snapshot(score=0.90),
    ]
    decision = evaluate_stop(
        run,
        _snapshot(score=0.90),
        [ImprovementCandidate(id="I-1", title="T", score=0.9)],
    )
    assert decision.stop is False


def test_no_diminishing_returns_with_short_history():
    run = _harness_run(iteration=2)
    run.quality_history = [_snapshot(score=0.90), _snapshot(score=0.91)]
    decision = evaluate_stop(
        run,
        _snapshot(score=0.91),
        [ImprovementCandidate(id="I-1", title="T", score=0.9)],
    )
    assert decision.stop is False
