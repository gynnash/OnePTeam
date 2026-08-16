import json
import threading
import time

from fastapi.testclient import TestClient

from onep.harness.persistence import load_harness_run, save_harness_run
from onep.web.server import create_app

from tests.test_web.fixtures import seed_project


def _parse_events(text: str) -> list[dict]:
    events = []
    for line in text.split("\n\n"):
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line[len("data: "):]))
    return events


def test_event_stream_pushes_flow_and_state_events(monkeypatch, tmp_path):
    monkeypatch.setattr("onep.web.runtime.POLL_INTERVAL", 0.01)
    monkeypatch.setattr("onep.web.runtime.HEARTBEAT_INTERVAL", 60.0)
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    flow_path = workspace / ".onep" / "harness" / "flow-events.jsonl"
    flow_path.unlink()  # start empty so tailing is observable

    client = TestClient(create_app())

    def feed():
        time.sleep(0.05)
        flow_path.write_text(json.dumps(
            {"type": "flow_transition",
             "payload": {"stage": "build", "iteration": 1}}) + "\n",
            encoding="utf-8")
        time.sleep(0.05)
        run = load_harness_run(workspace)
        run.status = "stopped"
        save_harness_run(run)

    thread = threading.Thread(target=feed)
    thread.start()
    try:
        with client.stream("GET", "/api/projects/demo/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            text = ""
            for chunk in response.iter_text():
                text += chunk
                if '"type": "flow"' in text and '"type": "state"' in text:
                    break
            events = _parse_events(text)
    finally:
        thread.join(timeout=5)

    kinds = {event["type"] for event in events}
    assert "flow" in kinds and "state" in kinds
    flow_event = next(event for event in events if event["type"] == "flow")
    assert flow_event["payload"]["stage"] == "build"
    state_event = next(event for event in events if event["type"] == "state")
    assert state_event["payload"]["status"] == "stopped"


def test_event_stream_404_for_missing_project(monkeypatch, tmp_path):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)
    client = TestClient(create_app())
    with client.stream("GET", "/api/projects/missing/events") as response:
        assert response.status_code == 404
