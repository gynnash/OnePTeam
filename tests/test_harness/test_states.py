import pytest

from onep.harness.states import HarnessFlow, HarnessStage


def test_flow_follows_legal_round_trip():
    flow = HarnessFlow()
    flow.start_iteration(1)
    flow.transition(HarnessStage.UNDERSTAND)
    flow.transition(HarnessStage.RESEARCH, {"skipped": True})
    flow.transition(HarnessStage.DESIGN)
    flow.transition(HarnessStage.PLAN)
    flow.transition(HarnessStage.BUILD)
    flow.transition(HarnessStage.VERIFY)
    flow.transition(HarnessStage.REVIEW)
    flow.transition(HarnessStage.REFLECT)
    flow.transition(HarnessStage.DISCOVER)
    flow.transition(HarnessStage.PRIORITIZE)
    flow.transition(HarnessStage.RESEARCH, {"skipped": True})
    flow.transition(HarnessStage.DESIGN)
    flow.transition(HarnessStage.PLAN)
    flow.transition(HarnessStage.STOP, {"reason": "goals_satisfied"})
    assert flow.stage is HarnessStage.STOP
    assert [e.stage for e in flow.events] == [
        HarnessStage.UNDERSTAND, HarnessStage.RESEARCH, HarnessStage.DESIGN,
        HarnessStage.PLAN, HarnessStage.BUILD, HarnessStage.VERIFY,
        HarnessStage.REVIEW, HarnessStage.REFLECT,
        HarnessStage.DISCOVER, HarnessStage.PRIORITIZE, HarnessStage.RESEARCH,
        HarnessStage.DESIGN, HarnessStage.PLAN, HarnessStage.STOP,
    ]


def test_illegal_transition_raises():
    flow = HarnessFlow()
    with pytest.raises(ValueError, match="Illegal harness transition"):
        flow.transition(HarnessStage.BUILD)


def test_plan_can_stop_when_no_work():
    flow = HarnessFlow()
    flow.transition(HarnessStage.UNDERSTAND)
    flow.transition(HarnessStage.RESEARCH)
    flow.transition(HarnessStage.DESIGN)
    flow.transition(HarnessStage.PLAN)
    flow.transition(HarnessStage.STOP, {"reason": "no_pending_work"})


def test_stop_is_terminal():
    flow = HarnessFlow()
    flow.transition(HarnessStage.UNDERSTAND)
    flow.transition(HarnessStage.RESEARCH)
    flow.transition(HarnessStage.DESIGN)
    flow.transition(HarnessStage.PLAN)
    flow.transition(HarnessStage.STOP)
    with pytest.raises(ValueError):
        flow.transition(HarnessStage.REFLECT)


def test_event_sink_receives_transitions():
    received = []
    flow = HarnessFlow(event_sink=lambda name, payload: received.append((name, payload)))
    flow.start_iteration(2)
    flow.transition(HarnessStage.UNDERSTAND)
    flow.transition(HarnessStage.RESEARCH, {"skipped": True})
    assert received == [
        ("flow_transition", {"stage": "understand", "iteration": 2}),
        ("flow_transition", {"stage": "research", "iteration": 2, "skipped": True}),
    ]


def test_fail_and_cancel_from_allowed_stages():
    flow = HarnessFlow()
    flow.transition(HarnessStage.UNDERSTAND)
    flow.fail("boom")
    assert flow.stage is HarnessStage.FAILED
    flow2 = HarnessFlow()
    flow2.transition(HarnessStage.UNDERSTAND)
    flow2.cancel()
    assert flow2.stage is HarnessStage.CANCELLED


def test_start_iteration_rejects_non_positive():
    flow = HarnessFlow()
    with pytest.raises(ValueError):
        flow.start_iteration(0)
