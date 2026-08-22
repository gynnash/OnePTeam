from onep.application import Capability, CapabilityRegistry
from onep.domain import JobStatus, Problem
from onep.execution import Worker
from onep.infrastructure import ControlStore


def queued(store, capability_id, action_id):
    return store.enqueue_job(
        capability_id,
        {},
        project_id="p1",
        run_id="r1",
        action_id=action_id,
    )


def test_worker_completes_job_and_records_result(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    registry = CapabilityRegistry([
        Capability("run.start", "Start", lambda *_: {"completed": True})
    ])
    job = queued(store, "run.start", "one")

    result = Worker(registry, store, "worker-1").run_once()

    assert result.id == job.id
    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {"completed": True}
    completed = [
        event for event in store.events(run_id="r1")
        if event["type"] == "action.completed"
    ]
    assert completed[0]["payload"]["result"] == {"completed": True}


def test_worker_records_stable_problem(tmp_path):
    store = ControlStore(tmp_path / "control.db")

    def fail(*_):
        raise Problem("git_dirty", "Git is dirty", "Commit files first")

    registry = CapabilityRegistry([Capability("run.start", "Start", fail)])
    queued(store, "run.start", "one")

    result = Worker(registry, store).run_once()

    assert result.status == JobStatus.FAILED
    assert result.error["code"] == "git_dirty"


def test_worker_touch_publishes_readiness(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    worker = Worker(CapabilityRegistry([]), store, "worker-ready")

    assert store.worker_health()["ready"] is False
    worker.touch()

    health = store.worker_health()
    assert health["ready"] is True
    assert health["worker_id"] == "worker-ready"
