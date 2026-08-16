from onep.harness.models import HarnessRun
from onep.harness.persistence import (
    clear_stop_request,
    harness_run_path,
    load_harness_run,
    save_harness_run,
    stop_requested,
)


def test_save_and_load_round_trip(tmp_path):
    run = HarnessRun(
        id="h-1", project_name="demo", workspace=str(tmp_path),
        mode="greenfield", original_goal="build value",
    )
    run.iteration = 3
    save_harness_run(run)
    assert harness_run_path(tmp_path).exists()
    restored = load_harness_run(tmp_path)
    assert restored is not None
    assert restored.id == "h-1"
    assert restored.iteration == 3
    assert restored.original_goal == "build value"


def test_load_returns_none_when_missing(tmp_path):
    assert load_harness_run(tmp_path) is None


def test_load_returns_none_for_corrupt_yaml(tmp_path):
    path = harness_run_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(":: not valid yaml")
    assert load_harness_run(tmp_path) is None


def test_stop_requested_flag(tmp_path):
    assert stop_requested(tmp_path) is False
    path = tmp_path / ".onep" / "harness" / "stop_requested"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    assert stop_requested(tmp_path) is True
    clear_stop_request(tmp_path)
    assert stop_requested(tmp_path) is False
