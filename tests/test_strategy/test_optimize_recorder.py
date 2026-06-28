from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import threading

import pytest
import yaml

from onep.strategy.optimize_models import (
    AttemptRecord,
    FailureReason,
    PlanCandidate,
    PlanRecord,
    PlanStatus,
    ReviewResult,
    RunRecord,
    RunStatus,
)
import onep.strategy.optimize_recorder as recorder_module
from onep.strategy.optimize_recorder import OptimizeRunRecorder


def make_run(tmp_path: Path) -> RunRecord:
    return RunRecord(
        id="run-1",
        project_name="demo",
        source_path=tmp_path / "source",
        base_commit="abc123",
        integration_branch="onep/optimize-run-1",
    )


def make_plan(item_id: str, title: str = "Cache fix") -> PlanRecord:
    return PlanRecord(
        candidate=PlanCandidate(
            id=item_id,
            title=title,
            fingerprint=f"fp-{item_id}",
        ),
        branch=f"onep/plan-{item_id}",
        base_commit="abc123",
    )


def make_attempt(number: int = 1) -> AttemptRecord:
    return AttemptRecord(
        number=number,
        branch="onep/plan-si-1",
        base_commit="abc123",
        changed_files={Path("src/cache.py")},
        feedback=["fix the race"],
    )


def integrate(plan: PlanRecord) -> None:
    for status in (
        PlanStatus.PLANNED,
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.REVIEWING,
        PlanStatus.COMMITTED,
        PlanStatus.INTEGRATED,
    ):
        plan.transition_to(status)


class FlushSpy:
    def __init__(self, wrapped, events, label):
        self.wrapped = wrapped
        self.events = events
        self.label = label

    def __enter__(self):
        self.wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)

    def write(self, content):
        return self.wrapped.write(content)

    def flush(self):
        self.events.append((f"{self.label}_flush", self.fileno()))
        return self.wrapped.flush()

    def fileno(self):
        return self.wrapped.fileno()

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


def test_initialization_immediately_persists_state_and_directories(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))

    state = yaml.safe_load((recorder.run_dir / "run.yaml").read_text("utf-8"))

    assert (recorder.run_dir / "plans").is_dir()
    assert state["id"] == "run-1"
    assert state["source_path"] == str(tmp_path / "source")


def test_initialization_flushes_fsyncs_and_atomically_replaces_state(
    tmp_path, monkeypatch
):
    events = []
    real_named_temporary_file = recorder_module.tempfile.NamedTemporaryFile
    real_fsync = os.fsync
    real_replace = os.replace

    def temporary_file_spy(*args, **kwargs):
        return FlushSpy(
            real_named_temporary_file(*args, **kwargs),
            events,
            "temporary",
        )

    def fsync_spy(fd):
        events.append(("fsync", fd))
        return real_fsync(fd)

    def replace_spy(source, destination):
        events.append(("replace", Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(
        recorder_module.tempfile,
        "NamedTemporaryFile",
        temporary_file_spy,
    )
    monkeypatch.setattr(recorder_module.os, "fsync", fsync_spy)
    monkeypatch.setattr(recorder_module.os, "replace", replace_spy)

    run_dir = tmp_path / "run"
    OptimizeRunRecorder(run_dir, make_run(tmp_path))

    replace_index, replace_event = next(
        (index, event)
        for index, event in enumerate(events)
        if event[0] == "replace" and event[2] == run_dir / "run.yaml"
    )
    source = replace_event[1]
    temporary_flush_index, temporary_flush = next(
        (index, event)
        for index, event in enumerate(events)
        if event[0] == "temporary_flush"
    )
    fsync_index = next(
        index
        for index, event in enumerate(events)
        if event == ("fsync", temporary_flush[1])
    )
    assert temporary_flush_index < fsync_index < replace_index
    assert source.parent == run_dir
    assert not source.exists()


def test_record_event_appends_and_refreshes_without_saving_local_state(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    recorder.run.total_cost = 1.25

    recorder.record_event("run_started", {"source": "/repo"})
    recorder.record_event("plan_failed", {"item_id": "si-1"})

    events = [
        json.loads(line)
        for line in (recorder.run_dir / "events.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    state = yaml.safe_load((recorder.run_dir / "run.yaml").read_text("utf-8"))
    assert [event["type"] for event in events] == [
        "run_started",
        "plan_failed",
    ]
    assert all(event["timestamp"].endswith("+00:00") for event in events)
    assert events[0]["payload"] == {"source": "/repo"}
    assert state["total_cost"] == 0.0
    assert recorder.run.total_cost == 0.0


def test_record_event_flushes_and_fsyncs_the_appended_line(
    tmp_path, monkeypatch
):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    events = []
    event_fd = []
    real_path_open = Path.open
    real_fsync = os.fsync

    def path_open_spy(path, *args, **kwargs):
        handle = real_path_open(path, *args, **kwargs)
        mode = kwargs.get("mode", args[0] if args else "r")
        if path == recorder.run_dir / "events.jsonl" and mode == "a":
            wrapped = FlushSpy(handle, events, "event")
            event_fd.append(wrapped.fileno())
            return wrapped
        return handle

    def fsync_spy(fd):
        events.append(("fsync", fd))
        return real_fsync(fd)

    monkeypatch.setattr(Path, "open", path_open_spy)
    monkeypatch.setattr(recorder_module.os, "fsync", fsync_spy)

    recorder.record_event("first", {})
    recorder.record_event("second", {})

    for fd in event_fd:
        flush_index = next(
            index
            for index, event in enumerate(events)
            if event == ("event_flush", fd)
        )
        fsync_index = next(
            index
            for index, event in enumerate(events)
            if index > flush_index and event == ("fsync", fd)
        )
        assert flush_index < fsync_index
    lines = (recorder.run_dir / "events.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["first", "second"]


def test_successful_and_failed_plans_coexist_without_duplicates(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    successful = make_plan("success")
    failed = make_plan("failure")
    integrate(successful)
    failed.fail(FailureReason.TEST_FAILED, "pytest returned 1")
    failed.transition_to(PlanStatus.ROLLED_BACK)

    recorder.save_plan(successful, "# Success")
    recorder.save_plan(failed, "# Failure")
    replacement = make_plan("success", title="Updated cache fix")
    integrate(replacement)
    replacement.commit_sha = "def456"
    recorder.save_plan(replacement, "# Updated success")

    assert len(recorder.run.plans) == 2
    assert recorder.run.plans[0].candidate.title == "Updated cache fix"
    assert recorder.run.plans[0].status == PlanStatus.INTEGRATED
    assert recorder.run.plans[0].commit_sha == "def456"
    assert recorder.run.plans[1].status == PlanStatus.ROLLED_BACK
    assert recorder.run.plans[1].failure_detail == "pytest returned 1"
    assert (
        recorder.run_dir / "plans" / "success" / "plan.md"
    ).read_text("utf-8") == "# Updated success"


def test_failed_plan_artifacts_survive_external_workspace_removal(tmp_path):
    source_dir = tmp_path / "source"
    worktree_dir = tmp_path / "worktree"
    source_dir.mkdir()
    worktree_dir.mkdir()
    (source_dir / "source.py").write_text("source = True\n", encoding="utf-8")
    (worktree_dir / "change.py").write_text("changed = True\n", encoding="utf-8")
    run = make_run(tmp_path)
    run.source_path = source_dir
    recorder = OptimizeRunRecorder(tmp_path / "history", run)
    plan = make_plan("si-2")
    plan.artifacts["worktree"] = str(worktree_dir)
    attempt = make_attempt()
    attempt.artifacts["source"] = str(source_dir)
    review = ReviewResult(
        passed=False,
        summary="blocking issue",
        findings=["src/cache.py:4 race"],
    )

    recorder.save_plan(plan, "# Retry Plan")
    recorder.save_attempt("si-2", attempt)
    recorder.save_review("si-2", 1, review)
    recorder.save_test_output("si-2", 1, "1 failed\n")
    recorder.save_diff("si-2", "diff --git a/a.py b/a.py\n")
    recorder.save_report("# Optimize report\n")

    shutil.rmtree(source_dir)
    shutil.rmtree(worktree_dir)

    plan_dir = recorder.run_dir / "plans" / "si-2"
    assert not source_dir.exists()
    assert not worktree_dir.exists()
    assert yaml.safe_load((plan_dir / "plan.yaml").read_text("utf-8"))[
        "candidate"
    ]["id"] == "si-2"
    assert yaml.safe_load((plan_dir / "plan.yaml").read_text("utf-8"))[
        "artifacts"
    ]["worktree"] == str(worktree_dir)
    assert yaml.safe_load(
        (plan_dir / "attempts" / "1" / "attempt.yaml").read_text("utf-8")
    )["number"] == 1
    assert json.loads(
        (plan_dir / "attempts" / "1" / "review.json").read_text("utf-8")
    )["passed"] is False
    assert (
        plan_dir / "attempts" / "1" / "test-output.txt"
    ).read_text("utf-8") == "1 failed\n"
    assert (plan_dir / "final.diff").read_text("utf-8").startswith("diff")
    assert (recorder.run_dir / "report.md").read_text("utf-8") == (
        "# Optimize report\n"
    )
    assert len(recorder.run.plans[0].attempts) == 1
    assert recorder.run.plans[0].attempts[0].number == attempt.number
    assert recorder.run.plans[0].attempts[0].review == review


def test_empty_and_repeated_artifact_saves_use_last_write_wins(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "")
    first_attempt = make_attempt()
    recorder.save_attempt("si-1", first_attempt)
    replacement_attempt = make_attempt()
    replacement_attempt.feedback = ["replacement"]
    recorder.save_attempt("si-1", replacement_attempt)

    recorder.save_review("si-1", 1, ReviewResult(passed=True))
    final_review = ReviewResult(
        passed=False,
        summary="replacement",
        findings=["blocking"],
    )
    recorder.save_review("si-1", 1, final_review)
    recorder.save_test_output("si-1", 1, "")
    recorder.save_test_output("si-1", 1, "latest test output")
    recorder.save_diff("si-1", "")
    recorder.save_diff("si-1", "latest diff")
    recorder.save_report("")
    recorder.save_report("latest report")

    plan_dir = recorder.run_dir / "plans" / "si-1"
    attempt_dir = plan_dir / "attempts" / "1"
    assert len(recorder.run.plans[0].attempts) == 1
    assert recorder.run.plans[0].attempts[0].feedback == ["replacement"]
    assert recorder.run.plans[0].attempts[0].review == final_review
    assert json.loads((attempt_dir / "review.json").read_text("utf-8")) == (
        final_review.to_dict()
    )
    assert (attempt_dir / "test-output.txt").read_text("utf-8") == (
        "latest test output"
    )
    assert (plan_dir / "final.diff").read_text("utf-8") == "latest diff"
    assert (recorder.run_dir / "report.md").read_text("utf-8") == (
        "latest report"
    )


def test_run_directories_are_independent(tmp_path):
    first_run = make_run(tmp_path)
    second_run = make_run(tmp_path)
    second_run.id = "run-2"
    first = OptimizeRunRecorder(tmp_path / "run-1", first_run)
    second = OptimizeRunRecorder(tmp_path / "run-2", second_run)

    first.save_plan(make_plan("first"), "# First")
    second.save_plan(make_plan("second"), "# Second")
    first.record_event("first_event", {})
    second.record_event("second_event", {})

    assert yaml.safe_load(
        (first.run_dir / "run.yaml").read_text("utf-8")
    )["id"] == "run-1"
    assert yaml.safe_load(
        (second.run_dir / "run.yaml").read_text("utf-8")
    )["id"] == "run-2"
    assert not (first.run_dir / "plans" / "second").exists()
    assert not (second.run_dir / "plans" / "first").exists()
    assert "first_event" in (first.run_dir / "events.jsonl").read_text("utf-8")
    assert "second_event" in (
        second.run_dir / "events.jsonl"
    ).read_text("utf-8")


def test_save_state_uses_atomic_replace_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    calls = []
    real_replace = os.replace

    def recording_replace(source, destination):
        calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)
    recorder.save_state()

    assert calls
    source, destination = calls[-1]
    assert source.parent == destination.parent == recorder.run_dir
    assert destination == recorder.run_dir / "run.yaml"
    assert not source.exists()


@pytest.mark.parametrize(
    "item_id",
    ["../escape", "nested/escape", r"..\escape", ".", "..", ""],
)
def test_item_id_path_traversal_is_rejected(tmp_path, item_id):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))

    with pytest.raises(ValueError, match="item_id"):
        recorder.save_plan(make_plan(item_id), "# unsafe")


def test_round_trip_load_restores_run_and_reports_corrupt_yaml(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "# Plan")
    recorder.save_attempt("si-1", make_attempt())

    loaded = OptimizeRunRecorder.load(run_dir)

    assert loaded.run == recorder.run
    assert loaded.run_dir == run_dir
    (run_dir / "run.yaml").write_text("[not: valid", encoding="utf-8")
    with pytest.raises(ValueError, match="Unable to load optimize run"):
        OptimizeRunRecorder.load(run_dir)


def test_rejects_symlinks_that_escape_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    try:
        (run_dir / "plans" / "escape").symlink_to(
            outside,
            target_is_directory=True,
        )
        (run_dir / "report.md").symlink_to(outside / "report.md")
    except OSError:
        pytest.skip("symlinks are not supported on this platform")

    with pytest.raises(ValueError, match="outside run_dir|symlink"):
        recorder.save_plan(make_plan("escape"), "# unsafe")
    with pytest.raises(ValueError, match="outside run_dir|symlink"):
        recorder.save_report("unsafe")

    assert list(outside.iterdir()) == []


def test_rejects_attempt_directory_symlink_that_escapes_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "# Plan")
    attempts = run_dir / "plans" / "si-1" / "attempts"
    try:
        attempts.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not supported on this platform")

    with pytest.raises(ValueError, match="outside run_dir|symlink"):
        recorder.save_attempt("si-1", make_attempt())

    assert list(outside.iterdir()) == []


def test_concurrent_recorders_merge_plans_without_lost_updates(tmp_path):
    run_dir = tmp_path / "run"
    first = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    second = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    barrier = threading.Barrier(2)
    failures = []

    def save_many(recorder, prefix):
        try:
            barrier.wait()
            for index in range(15):
                item_id = f"{prefix}-{index}"
                recorder.save_plan(make_plan(item_id), f"# {item_id}")
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            failures.append(exc)

    threads = [
        threading.Thread(target=save_many, args=(first, "first")),
        threading.Thread(target=save_many, args=(second, "second")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    loaded = OptimizeRunRecorder.load(run_dir)
    assert {plan.candidate.id for plan in loaded.run.plans} == {
        f"{prefix}-{index}"
        for prefix in ("first", "second")
        for index in range(15)
    }


def test_event_uses_append_fd_and_retries_partial_byte_writes(
    tmp_path, monkeypatch
):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    real_open = os.open
    real_write = os.write
    real_fsync = os.fsync
    opened_flags = []
    append_fds = []
    fsynced_fds = []
    writes = []

    def open_spy(path, flags, mode=0o777):
        opened_flags.append(flags)
        fd = real_open(path, flags, mode)
        if flags & os.O_APPEND:
            append_fds.append(fd)
        return fd

    def partial_write(fd, data):
        writes.append(data)
        chunk = data[: max(1, len(data) // 2)]
        return real_write(fd, chunk)

    def fsync_spy(fd):
        fsynced_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(recorder_module.os, "open", open_spy)
    monkeypatch.setattr(recorder_module.os, "write", partial_write)
    monkeypatch.setattr(recorder_module.os, "fsync", fsync_spy)

    recorder.record_event("路径", {"value": Path("src/a.py")})

    assert opened_flags
    assert any(flags & os.O_APPEND for flags in opened_flags)
    assert any(
        flags & os.O_APPEND and flags & os.O_CREAT
        for flags in opened_flags
    )
    assert all(isinstance(chunk, bytes) for chunk in writes)
    assert append_fds
    assert set(append_fds).issubset(fsynced_fds)
    event = json.loads(
        (recorder.run_dir / "events.jsonl").read_text("utf-8")
    )
    assert event["payload"] == {"value": "src/a.py"}


def test_atomic_write_fsyncs_parent_directory_after_replace(
    tmp_path, monkeypatch
):
    fsynced_directories = []
    real_fsync = os.fsync

    def fsync_spy(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            fsynced_directories.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(recorder_module.os, "fsync", fsync_spy)

    OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))

    assert fsynced_directories


def test_load_recovers_plan_committed_before_run_state(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("orphan"), "# Orphan")
    state = yaml.safe_load((run_dir / "run.yaml").read_text("utf-8"))
    state["plans"] = []
    (run_dir / "run.yaml").write_text(
        yaml.safe_dump(state),
        encoding="utf-8",
    )

    loaded = OptimizeRunRecorder.load(run_dir)

    assert [plan.candidate.id for plan in loaded.run.plans] == ["orphan"]
    repaired = yaml.safe_load((run_dir / "run.yaml").read_text("utf-8"))
    assert repaired["plans"][0]["candidate"]["id"] == "orphan"


def test_load_reports_corrupt_child_plan_clearly(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("broken"), "# Broken")
    (run_dir / "plans" / "broken" / "plan.yaml").write_text(
        "[invalid: yaml",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unable to load plan record.*broken"):
        OptimizeRunRecorder.load(run_dir)


def test_save_plan_merges_persisted_fields_from_older_record(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    persisted = make_plan("si-1", "Original")
    integrate(persisted)
    persisted.commit_sha = "commit-1"
    persisted.failure_detail = "historical detail"
    persisted.artifacts = {"diff": "final.diff", "old": "kept"}
    persisted_attempt = make_attempt()
    persisted_attempt.review = ReviewResult(
        passed=True,
        summary="approved",
    )
    persisted_attempt.artifacts = {"review": "review.json"}
    persisted.attempts = [persisted_attempt]
    recorder.save_plan(persisted, "# Original")

    update = make_plan("si-1", "Updated")
    update.artifacts = {"new": "added"}
    update.attempts = [make_attempt()]
    recorder.save_plan(update, "# Updated")

    merged = recorder.run.plans[0]
    assert merged.candidate.title == "Updated"
    assert merged.status == PlanStatus.INTEGRATED
    assert merged.commit_sha == "commit-1"
    assert merged.failure_detail == "historical detail"
    assert merged.attempts[0].review == persisted_attempt.review
    assert merged.attempts[0].artifacts == {"review": "review.json"}
    assert merged.artifacts == {
        "diff": "final.diff",
        "old": "kept",
        "new": "added",
    }


def test_supported_values_are_normalized_before_state_mutation(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    plan = make_plan("safe")
    plan.artifacts = {
        "path": Path("src/a.py"),
        "when": datetime(2026, 6, 29, tzinfo=timezone.utc),
        "tags": {"b", "a"},
    }

    recorder.save_plan(plan, "# Safe")

    artifacts = recorder.run.plans[0].artifacts
    assert artifacts == {
        "path": "src/a.py",
        "when": "2026-06-29T00:00:00+00:00",
        "tags": ["a", "b"],
    }


def test_unsupported_plan_value_does_not_pollute_memory(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    before = recorder.run.to_dict()
    plan = make_plan("unsafe")
    plan.artifacts = {"object": object()}

    with pytest.raises(TypeError, match="Unsupported"):
        recorder.save_plan(plan, "# Unsafe")

    assert recorder.run.to_dict() == before
    assert not (recorder.run_dir / "plans" / "unsafe").exists()


def test_failed_plan_write_does_not_pollute_memory(
    tmp_path, monkeypatch
):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    before = recorder.run.to_dict()
    real_write = recorder_module._atomic_yaml_write

    def fail_plan_write(path, data):
        if path.name == "plan.yaml":
            raise OSError("injected write failure")
        return real_write(path, data)

    monkeypatch.setattr(
        recorder_module,
        "_atomic_yaml_write",
        fail_plan_write,
    )

    with pytest.raises(OSError, match="injected"):
        recorder.save_plan(make_plan("failed-write"), "# Plan")

    assert recorder.run.to_dict() == before


def test_invalid_attempt_and_review_do_not_mutate_existing_state(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "# Plan")
    recorder.save_attempt("si-1", make_attempt())
    before = recorder.run.to_dict()
    invalid_attempt = make_attempt(2)
    invalid_attempt.artifacts = {"bad": object()}
    invalid_review = ReviewResult(passed=False, findings=[object()])

    with pytest.raises(TypeError, match="Unsupported"):
        recorder.save_attempt("si-1", invalid_attempt)
    assert recorder.run.to_dict() == before
    with pytest.raises(TypeError, match="Unsupported"):
        recorder.save_review("si-1", 1, invalid_review)
    assert recorder.run.to_dict() == before


def test_stale_recorder_cannot_regress_completed_run_to_running(tmp_path):
    run_dir = tmp_path / "run"
    current = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    stale = OptimizeRunRecorder(run_dir, make_run(tmp_path))

    current.run.status = RunStatus.COMPLETED
    current.run.failure_detail = "final detail"
    current.save_state()
    stale.run.status = RunStatus.RUNNING
    stale.run.failure_detail = ""
    stale.save_state()

    loaded = OptimizeRunRecorder.load(run_dir)
    assert loaded.run.status == RunStatus.COMPLETED
    assert loaded.run.failure_detail == "final detail"


def test_stale_recorder_cannot_regress_integrated_plan_to_developing(tmp_path):
    run_dir = tmp_path / "run"
    current = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    stale = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    integrated = make_plan("si-1")
    integrate(integrated)
    integrated.commit_sha = "final-commit"
    current.save_plan(integrated, "# Integrated")

    stale_plan = make_plan("si-1")
    stale_plan.transition_to(PlanStatus.PLANNED)
    stale_plan.transition_to(PlanStatus.DEVELOPING)
    stale.save_plan(stale_plan, "# Stale")

    loaded = OptimizeRunRecorder.load(run_dir)
    plan = loaded.run.plans[0]
    assert plan.status == PlanStatus.INTEGRATED
    assert plan.commit_sha == "final-commit"


def test_plan_merge_rejects_forward_priority_with_no_legal_transition(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    failed = make_plan("si-1")
    failed.fail(FailureReason.TEST_FAILED, "final failure")
    recorder.save_plan(failed, "# Failed")
    unrelated_integrated = make_plan("si-1")
    integrate(unrelated_integrated)

    recorder.save_plan(unrelated_integrated, "# Illegal successor")

    loaded = OptimizeRunRecorder.load(run_dir)
    assert loaded.run.plans[0].status == PlanStatus.FAILED
    assert loaded.run.plans[0].failure_detail == "final failure"


def test_plan_merge_persists_legal_repair_loop_transitions(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    repairing = make_plan("si-1")
    for status in (
        PlanStatus.PLANNED,
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.REPAIRING,
    ):
        repairing.transition_to(status)
    recorder.save_plan(repairing, "# Repairing")

    developing = PlanRecord.from_dict(repairing.to_dict())
    developing.transition_to(PlanStatus.DEVELOPING)
    recorder.save_plan(developing, "# Developing again")
    testing = PlanRecord.from_dict(developing.to_dict())
    testing.transition_to(PlanStatus.TESTING)
    recorder.save_plan(testing, "# Testing again")

    loaded = OptimizeRunRecorder.load(run_dir)
    assert loaded.run.plans[0].status == PlanStatus.TESTING


def test_load_merges_complete_child_plan_when_run_state_write_failed(
    tmp_path, monkeypatch
):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("si-1", "Original"), "# Original")
    updated = make_plan("si-1", "Recovered title")
    integrate(updated)
    updated.commit_sha = "recovered-commit"
    updated.failure_detail = "preserved detail"
    updated.artifacts = {"diff": "final.diff"}
    updated.attempts = [make_attempt()]
    real_write = recorder_module._atomic_yaml_write

    def fail_run_state(path, data):
        if path.name == "run.yaml":
            raise OSError("injected run state failure")
        return real_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(
            recorder_module,
            "_atomic_yaml_write",
            fail_run_state,
        )
        with pytest.raises(OSError, match="injected run state failure"):
            recorder.save_plan(updated, "# Updated child")

    loaded = OptimizeRunRecorder.load(run_dir)

    recovered = loaded.run.plans[0]
    assert recovered.candidate.title == "Recovered title"
    assert recovered.status == PlanStatus.INTEGRATED
    assert recovered.commit_sha == "recovered-commit"
    assert recovered.failure_detail == "preserved detail"
    assert recovered.artifacts == {"diff": "final.diff"}
    assert [attempt.number for attempt in recovered.attempts] == [1]
    repaired_state = yaml.safe_load(
        (run_dir / "run.yaml").read_text("utf-8")
    )
    assert repaired_state["plans"][0] == recovered.to_dict()


def test_record_event_refreshes_stale_recorder_without_regressing_plan(
    tmp_path,
):
    run_dir = tmp_path / "run"
    first = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    developing = make_plan("si-1")
    developing.transition_to(PlanStatus.PLANNED)
    developing.transition_to(PlanStatus.DEVELOPING)
    first.save_plan(developing, "# Developing")
    stale = OptimizeRunRecorder.load(run_dir)

    testing = PlanRecord.from_dict(first.run.plans[0].to_dict())
    testing.transition_to(PlanStatus.TESTING)
    first.save_plan(testing, "# Testing")
    repairing = PlanRecord.from_dict(first.run.plans[0].to_dict())
    repairing.transition_to(PlanStatus.REPAIRING)
    first.save_plan(repairing, "# Repairing")

    stale.record_event("observer_note", {"message": "still running"})

    disk = OptimizeRunRecorder.load(run_dir)
    assert disk.run.plans[0].status == PlanStatus.REPAIRING
    assert stale.run.plans[0].status == PlanStatus.REPAIRING
    event = json.loads(
        (run_dir / "events.jsonl").read_text("utf-8").splitlines()[-1]
    )
    assert event["type"] == "observer_note"


def test_active_backward_repair_transition_from_last_seen_is_saved(tmp_path):
    run_dir = tmp_path / "run"
    writer = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    repairing = make_plan("si-1")
    for status in (
        PlanStatus.PLANNED,
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.REPAIRING,
    ):
        repairing.transition_to(status)
    writer.save_plan(repairing, "# Repairing")
    active = OptimizeRunRecorder.load(run_dir)
    developing = PlanRecord.from_dict(active.run.plans[0].to_dict())
    developing.transition_to(PlanStatus.DEVELOPING)

    active.save_plan(developing, "# Developing again")

    loaded = OptimizeRunRecorder.load(run_dir)
    assert loaded.run.plans[0].status == PlanStatus.DEVELOPING
    assert active.run.plans[0].status == PlanStatus.DEVELOPING


def test_stale_reviewer_repair_cannot_overwrite_integrated_plan(tmp_path):
    run_dir = tmp_path / "run"
    owner = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    reviewing = make_plan("si-1")
    for status in (
        PlanStatus.PLANNED,
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.REVIEWING,
    ):
        reviewing.transition_to(status)
    reviewing.attempts = [make_attempt()]
    owner.save_plan(reviewing, "# Reviewing")
    integrator = OptimizeRunRecorder.load(run_dir)
    stale_reviewer = OptimizeRunRecorder.load(run_dir)

    committed = PlanRecord.from_dict(integrator.run.plans[0].to_dict())
    committed.transition_to(PlanStatus.COMMITTED)
    committed.commit_sha = "commit-final"
    committed.artifacts = {"review": "approved.json"}
    committed.attempts[0].review = ReviewResult(
        passed=True,
        summary="current review",
    )
    committed.attempts[0].artifacts = {"evidence": "current"}
    integrator.save_plan(committed, "# Committed")
    integrated = PlanRecord.from_dict(integrator.run.plans[0].to_dict())
    integrated.transition_to(PlanStatus.INTEGRATED)
    integrator.save_plan(integrated, "# Integrated")

    repairing = PlanRecord.from_dict(
        stale_reviewer.run.plans[0].to_dict()
    )
    repairing.transition_to(PlanStatus.REPAIRING)
    repairing.artifacts = {"stale_note": "retry"}
    repairing.attempts[0].feedback = ["stale repair"]
    repairing.attempts[0].artifacts = {"evidence": "stale"}
    stale_reviewer.save_plan(repairing, "# Stale repair")

    final = OptimizeRunRecorder.load(run_dir).run.plans[0]
    assert final.status == PlanStatus.INTEGRATED
    assert final.commit_sha == "commit-final"
    assert [attempt.number for attempt in final.attempts] == [1]
    assert final.attempts[0].review.summary == "current review"
    assert final.attempts[0].artifacts == {"evidence": "current"}
    assert final.artifacts == {
        "review": "approved.json",
        "stale_note": "retry",
    }


def test_nonterminal_conflict_keeps_persisted_when_transition_is_illegal(
    tmp_path,
):
    run_dir = tmp_path / "run"
    owner = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    reviewing = make_plan("si-1")
    for status in (
        PlanStatus.PLANNED,
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.REVIEWING,
    ):
        reviewing.transition_to(status)
    owner.save_plan(reviewing, "# Reviewing")
    first = OptimizeRunRecorder.load(run_dir)
    stale = OptimizeRunRecorder.load(run_dir)

    committed = PlanRecord.from_dict(first.run.plans[0].to_dict())
    committed.transition_to(PlanStatus.COMMITTED)
    committed.commit_sha = "committed-evidence"
    committed.artifacts = {"current": "kept"}
    first.save_plan(committed, "# Committed")
    repairing = PlanRecord.from_dict(stale.run.plans[0].to_dict())
    repairing.transition_to(PlanStatus.REPAIRING)
    repairing.artifacts = {"stale": "merged"}
    stale.save_plan(repairing, "# Repairing")

    final = OptimizeRunRecorder.load(run_dir).run.plans[0]
    assert final.status == PlanStatus.COMMITTED
    assert final.commit_sha == "committed-evidence"
    assert final.artifacts == {"current": "kept", "stale": "merged"}


def test_nonterminal_conflict_accepts_transition_allowed_from_persisted(
    tmp_path,
):
    run_dir = tmp_path / "run"
    owner = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    developing = make_plan("si-1")
    developing.transition_to(PlanStatus.PLANNED)
    developing.transition_to(PlanStatus.DEVELOPING)
    owner.save_plan(developing, "# Developing")
    first = OptimizeRunRecorder.load(run_dir)
    stale = OptimizeRunRecorder.load(run_dir)

    testing = PlanRecord.from_dict(first.run.plans[0].to_dict())
    testing.transition_to(PlanStatus.TESTING)
    testing.artifacts = {"tests": "running"}
    first.save_plan(testing, "# Testing")
    failed = PlanRecord.from_dict(stale.run.plans[0].to_dict())
    failed.fail(FailureReason.TEST_FAILED, "failed from stale baseline")
    stale.save_plan(failed, "# Failed")

    final = OptimizeRunRecorder.load(run_dir).run.plans[0]
    assert final.status == PlanStatus.FAILED
    assert final.failure_detail == "failed from stale baseline"
    assert final.artifacts == {"tests": "running"}


def test_save_attempt_writes_merged_review_to_all_state_copies(tmp_path):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "# Plan")
    recorder.save_attempt("si-1", make_attempt())
    review = ReviewResult(passed=True, summary="approved")
    recorder.save_review("si-1", 1, review)

    recorder.save_attempt("si-1", make_attempt())

    attempt_dir = run_dir / "plans" / "si-1" / "attempts" / "1"
    attempt_state = yaml.safe_load(
        (attempt_dir / "attempt.yaml").read_text("utf-8")
    )
    plan_state = yaml.safe_load(
        (run_dir / "plans" / "si-1" / "plan.yaml").read_text("utf-8")
    )
    run_state = yaml.safe_load((run_dir / "run.yaml").read_text("utf-8"))
    assert attempt_state["review"]["summary"] == "approved"
    assert plan_state["attempts"][0]["review"]["summary"] == "approved"
    assert run_state["plans"][0]["attempts"][0]["review"]["summary"] == (
        "approved"
    )


def test_load_recovers_review_artifact_after_state_write_failure(
    tmp_path, monkeypatch
):
    run_dir = tmp_path / "run"
    recorder = OptimizeRunRecorder(run_dir, make_run(tmp_path))
    recorder.save_plan(make_plan("si-1"), "# Plan")
    recorder.save_attempt("si-1", make_attempt())
    recorder.save_test_output("si-1", 1, "tests passed")
    recorder.save_diff("si-1", "final diff")
    real_write = recorder_module._atomic_yaml_write

    def fail_attempt_state(path, data):
        if path.name == "attempt.yaml":
            raise OSError("injected state failure")
        return real_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(
            recorder_module,
            "_atomic_yaml_write",
            fail_attempt_state,
        )
        with pytest.raises(OSError, match="injected state failure"):
            recorder.save_review(
                "si-1",
                1,
                ReviewResult(passed=True, summary="recovered review"),
            )

    loaded = OptimizeRunRecorder.load(run_dir)

    recovered = loaded.run.plans[0].attempts[0]
    assert recovered.review is not None
    assert recovered.review.summary == "recovered review"
    attempt_dir = run_dir / "plans" / "si-1" / "attempts" / "1"
    attempt_state = yaml.safe_load(
        (attempt_dir / "attempt.yaml").read_text("utf-8")
    )
    plan_state = yaml.safe_load(
        (run_dir / "plans" / "si-1" / "plan.yaml").read_text("utf-8")
    )
    run_state = yaml.safe_load((run_dir / "run.yaml").read_text("utf-8"))
    assert attempt_state["review"]["summary"] == "recovered review"
    assert plan_state["attempts"][0]["review"]["summary"] == (
        "recovered review"
    )
    assert run_state["plans"][0]["attempts"][0]["review"]["summary"] == (
        "recovered review"
    )
    assert (attempt_dir / "test-output.txt").read_text("utf-8") == (
        "tests passed"
    )
    assert (run_dir / "plans" / "si-1" / "final.diff").read_text(
        "utf-8"
    ) == "final diff"
def test_plan_summary_indexes_are_written(tmp_path):
    recorder = OptimizeRunRecorder(tmp_path / "run", make_run(tmp_path))
    recorder.save_plan(make_plan("si-index"), "# Plan")
    recorder.save_attempt("si-index", make_attempt())
    plan_dir = recorder.run_dir / "plans" / "si-index"
    assert (plan_dir / "metadata.yaml").exists()
    assert (plan_dir / "state.yaml").exists()
    lines = (plan_dir / "attempts.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["number"] == 1
