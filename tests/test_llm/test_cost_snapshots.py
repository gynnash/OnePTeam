from onep.llm.adapters import TokenUsage
from onep.llm.cost import CostTracker


def test_tracker_records_each_usage_once(monkeypatch):
    monkeypatch.setattr("onep.llm.cost._get_price", lambda model, kind: 1.0)
    tracker = CostTracker(budget=1.0)
    usage = TokenUsage(1000, 500, 1500)
    entry = tracker.record_usage("developer", "model", usage)
    assert entry.cost == 0.0015
    assert tracker.spent == 0.0015
    assert tracker.record_usage("developer", "model", usage).cost == 0


def test_reservation_accounts_for_pending_calls():
    tracker = CostTracker(budget=0.01)
    tracker.add_cost(0.009)
    assert not tracker.can_reserve(0.002)
    assert tracker.reserve(0.001)
    assert not tracker.can_reserve(0.0001)
    tracker.release(0.001)
    assert tracker.can_reserve(0.001)
