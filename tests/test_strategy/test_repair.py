from onep.strategy.repair import AttemptStagnationDetector, RepairBrief


def brief(diff="same", error="failed"):
    return RepairBrief.build(
        failure_type="test_failed",
        raw_error=error,
        relevant_files=["app.py"],
        diff=diff,
        failing_command="pytest",
    )


def test_repair_brief_is_structured_and_bounded():
    value = brief(error="line 1\nline 2")
    assert value.failure_type == "test_failed"
    assert value.failing_command == "pytest"
    assert "line 2" in value.primary_error
    assert "suggested_next_action" in value.to_dict()


def test_stagnation_requires_same_diff_and_failure_repeated():
    detector = AttemptStagnationDetector(repeat_limit=2)
    assert detector.observe(brief()) is False
    assert detector.observe(brief(diff="changed")) is False
    assert detector.observe(brief(diff="changed")) is True


def test_new_failure_resets_stagnation():
    detector = AttemptStagnationDetector(repeat_limit=2)
    assert detector.observe(brief()) is False
    assert detector.observe(brief(error="different")) is False
