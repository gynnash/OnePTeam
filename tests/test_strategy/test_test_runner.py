from onep.strategy.test_runner import PlanTestRunner


def test_runner_uses_exit_code_not_output(tmp_path):
    result = PlanTestRunner(timeout=5).run(
        tmp_path,
        ["python -c \"import sys; print('passed'); sys.exit(1)\""],
    )
    assert not result.passed
    assert result.commands[0].exit_code == 1
    assert "passed" in result.commands[0].stdout


def test_runner_stops_after_timeout(tmp_path):
    result = PlanTestRunner(timeout=0.05).run(
        tmp_path, ["python -c \"import time; time.sleep(1)\""]
    )
    assert not result.passed
    assert result.commands[0].timed_out
