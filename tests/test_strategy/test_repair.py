from onep.strategy.repair import (
    AttemptStagnationDetector,
    RepairBrief,
    classify_failure,
    extract_relevant_files,
    has_mutating_action,
)


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


def test_pytest_repair_brief_keeps_all_failed_tests_and_assertions():
    raw = """
E AssertionError: assert 1 == 10
tests/unit/test_cluster.py:63: AssertionError
E AssertionError: assert 12.5 == 15.0
tests/unit/test_heat_score.py:54: AssertionError
FAILED tests/unit/test_cluster.py::test_no_overlap
FAILED tests/unit/test_heat_score.py::test_declining
4 failed, 64 passed
"""
    value = brief(error=raw)

    assert "test_no_overlap" in value.primary_error
    assert "test_declining" in value.primary_error
    assert "assert 1 == 10" in value.primary_error
    assert "assert 12.5 == 15.0" in value.primary_error


def test_mutating_action_detection_distinguishes_reads_and_writes():
    read = (
        {
            "type": "tool_requested",
            "payload": {"tool_name": "file_read", "tool_args": {"path": "a.py"}},
        },
    )
    write = (
        {
            "type": "tool_requested",
            "payload": {"tool_name": "edit", "tool_args": {"file_path": "a.py"}},
        },
    )

    assert not has_mutating_action(read)
    assert has_mutating_action(write)


def test_failure_classification_and_relevant_file_extraction():
    raw = (
        "ERROR tests/test_collectors.py - import file mismatch\n"
        "tests/test_collectors/test_arxiv.py:27: ImportError"
    )

    value = RepairBrief.build(
        "test_failed",
        raw,
        ["output/weekly_scan.log", "src/main.py"],
        "",
        failing_command="pytest tests/test_collectors.py::test_exports -q",
    )

    assert classify_failure(raw) == "collection_conflict"
    assert value.failure_category == "collection_conflict"
    assert "tests/test_collectors.py" in value.relevant_files
    assert "tests/test_collectors/test_arxiv.py" in value.relevant_files
    assert "output/weekly_scan.log" not in value.relevant_files
    assert extract_relevant_files("output/run.log", "pytest -q") == []


def test_runtime_only_diff_does_not_change_stagnation_signature():
    code = "diff --git a/src/app.py b/src/app.py\n+VALUE = 1\n"
    runtime = (
        code
        + "diff --git a/output/run.log b/output/run.log\n"
        + "+2026-07-20 runtime\n"
    )

    assert brief(diff=code).diff_sha == brief(diff=runtime).diff_sha
