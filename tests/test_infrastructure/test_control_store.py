from datetime import datetime, timedelta, timezone
import sqlite3

from onep.domain import JobStatus, RunRecord, RunStatus
from onep.infrastructure import ControlStore


def enqueue(store, action, project="p1", mutating=True):
    return store.enqueue_job(
        "run.start",
        {"action": action},
        project_id=project,
        run_id="r1",
        action_id=action,
        mutating=mutating,
    )


def test_events_have_stable_sequence_and_filters(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    one = store.append_event("run.started", {"n": 1}, project_id="p1")
    two = store.append_event("run.started", {"n": 2}, project_id="p2")
    three = store.append_event("stage.started", {"n": 3}, project_id="p1")

    assert one < two < three
    assert [event["sequence"] for event in store.events(after=one)] == [two, three]
    assert [event["type"] for event in store.events(project_id="p1")] == [
        "run.started",
        "stage.started",
    ]


def test_claim_serializes_mutating_jobs_per_project(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    first = enqueue(store, "a")
    second = enqueue(store, "b")
    other = enqueue(store, "c", project="p2")

    assert store.claim_job("worker-1").id == first.id
    assert store.claim_job("worker-2").id == other.id
    assert store.claim_job("worker-3") is None

    store.finish_job(first.id, succeeded=True)
    assert store.claim_job("worker-3").id == second.id
    assert [job.id for job in store.jobs(2)] == [other.id, second.id]


def test_expired_lease_returns_job_to_queue(tmp_path):
    path = tmp_path / "control.db"
    store = ControlStore(path)
    job = enqueue(store, "a")
    assert store.claim_job("dead-worker").status == JobStatus.RUNNING
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE v2_jobs SET lease_until = ? WHERE id = ?", (expired, job.id)
        )

    recovered = store.claim_job("new-worker")

    assert recovered.id == job.id
    assert recovered.attempts == 2
    assert recovered.lease_owner == "new-worker"


def test_cancel_and_run_crud(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    queued = enqueue(store, "queued")
    assert store.request_cancel(queued.id).status == JobStatus.CANCELLED

    run = store.create_run(RunRecord(
        id="r1",
        project_id="p1",
        goal_version=1,
        workflow="mixed",
        options={"max_rounds": 10},
    ))
    assert run.status == RunStatus.PENDING
    updated = store.update_run("r1", status=RunStatus.RUNNING, stage="understand")
    assert updated.status == RunStatus.RUNNING
    assert updated.stage == "understand"
    assert store.latest_run_for_project("p1").id == "r1"
    assert store.latest_run_for_project("missing") is None
