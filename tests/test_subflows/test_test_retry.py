from pathlib import Path

from onep.subflows.test_retry import build_test_retry_graph, run_test_loop


def test_test_loop_passes_on_successful_command(tmp_path: Path):
    result = run_test_loop(tmp_path, test_command="echo all good && exit 0")
    assert result["passed"] is True
    assert result["status"] == "passed"


def test_test_loop_escalates_after_max_retries(tmp_path: Path):
    result = run_test_loop(
        tmp_path, test_command="echo fail && exit 1", max_retries=2,
    )
    assert result["passed"] is False
    assert result["status"] == "escalated"


def test_graph_compiles():
    graph = build_test_retry_graph()
    assert graph is not None
