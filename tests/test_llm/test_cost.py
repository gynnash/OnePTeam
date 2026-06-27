from onep.llm.cost import estimate_scan_cost, estimate_analyze_cost, CostTracker


def test_estimate_scan_cost():
    cost = estimate_scan_cost(file_count=500, batch_size=50)
    assert cost > 0


def test_estimate_analyze_cost():
    cost = estimate_analyze_cost(strategy_file_count=20)
    assert cost > 0


def test_cost_tracker_within_budget():
    tracker = CostTracker(budget=5.00)
    assert tracker.can_continue()
    tracker.add_cost(2.00)
    assert tracker.remaining == 3.00
    assert tracker.can_continue()


def test_cost_tracker_exceeded():
    tracker = CostTracker(budget=2.00)
    tracker.add_cost(2.50)
    assert not tracker.can_continue()


def test_cost_tracker_zero_budget_always_ok():
    tracker = CostTracker(budget=0)
    tracker.add_cost(100)
    assert tracker.can_continue()


def test_cost_tracker_add_usage():
    tracker = CostTracker(budget=1.00)
    tracker.add_usage(prompt_tokens=1000000, completion_tokens=1000000, model="deepseek/deepseek-chat")
    assert tracker.spent > 0
