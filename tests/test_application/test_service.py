from onep.application import (
    ApplicationService,
    Capability,
    CapabilityRegistry,
    RequestContext,
)
from onep.infrastructure import ControlStore


def test_immediate_action_emits_requested_and_completed(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    registry = CapabilityRegistry([
        Capability("project.echo", "Echo", lambda body, _: {"value": body["value"]})
    ])
    service = ApplicationService(registry, store)

    result = service.execute(
        "project.echo",
        {"value": "ok"},
        context=RequestContext(project_id="p1", actor="alice"),
    )

    assert result.status == "succeeded"
    assert result.data == {"value": "ok"}
    assert [event["type"] for event in store.events(project_id="p1")] == [
        "action.requested",
        "action.completed",
    ]


def test_background_action_is_idempotent(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    registry = CapabilityRegistry([
        Capability(
            "run.start",
            "Start run",
            lambda body, _: body,
            mutating=True,
            background=True,
        )
    ])
    service = ApplicationService(registry, store)
    context = RequestContext(project_id="p1", run_id="r1")

    first = service.execute(
        "run.start", {"goal": "x"}, context=context, action_id="same-action"
    )
    second = service.execute(
        "run.start", {"goal": "x"}, context=context, action_id="same-action"
    )

    assert first.job_id == second.job_id
    assert first.status == second.status == "queued"
