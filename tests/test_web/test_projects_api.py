import json
from pathlib import Path

from fastapi.testclient import TestClient

from onep.persistence.models import Project, ProjectMode
from onep.web.server import create_app

from tests.test_web.fixtures import seed_project


def test_projects_list(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    client = TestClient(create_app())
    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()["projects"]
    assert projects[0]["name"] == "demo"
    assert projects[0]["harness"]["stage"] == "stop"
    assert projects[0]["harness"]["stop_reason"] == "goals_satisfied"


def test_create_project_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)
    monkeypatch.setattr("onep.web.runtime.workspace_for",
                        lambda name: tmp_path / f"ws-{name}")
    spawned = {}
    monkeypatch.setattr("onep.web.runtime.spawn_run",
                        lambda name, workspace: spawned.update(name=name, workspace=str(workspace)) or {"pid": 42, "started": True})
    client = TestClient(create_app())
    response = client.post("/api/projects",
                           json={"requirement": "build a cli", "name": "cli-1"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "cli-1"
    assert body["spawn"]["pid"] == 42
    assert spawned == {"name": "cli-1", "workspace": str(tmp_path / "ws-cli-1")}


def test_create_project_requires_requirement(tmp_path, monkeypatch):
    client = TestClient(create_app())
    response = client.post("/api/projects", json={"name": "x"})
    assert response.status_code == 400


def test_create_project_duplicate_name_conflicts(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    monkeypatch.setattr("onep.web.api.projects.create_project", lambda *a, **k: Project(
        name="demo", mode=ProjectMode.GREENFIELD, workspace_path=""))
    client = TestClient(create_app())
    response = client.post("/api/projects",
                           json={"requirement": "dup", "name": "demo"})
    assert response.status_code == 409


def test_run_detail_endpoint(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    client = TestClient(create_app())
    response = client.get("/api/projects/demo")
    assert response.status_code == 200
    detail = response.json()
    assert detail["stop_state"]["reason"] == "goals_satisfied"
    assert detail["stage_history"][-1]["stage"] == "stop"
    assert client.get("/api/projects/missing").status_code == 404


def test_log_endpoint(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    client = TestClient(create_app())
    response = client.get("/api/projects/demo/log?offset=1&limit=1")
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["offset"] == 1
    assert body["next_offset"] == 2


def test_stop_endpoint_writes_flag(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    client = TestClient(create_app())
    response = client.post("/api/projects/demo/stop")
    assert response.status_code == 200
    assert (workspace / ".onep" / "harness" / "stop_requested").exists()
