import json
from pathlib import Path

import pytest
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


def test_create_project_rejects_traversal_names(tmp_path, monkeypatch):
    client = TestClient(create_app())
    for name in ["..", "../evil", "../../../../tmp/evil", "a/b", "bad name"]:
        response = client.post("/api/projects", json={"requirement": "x", "name": name})
        assert response.status_code == 400, (name, response.text)


def test_workspace_for_rejects_names_escaping_managed_root(tmp_path, monkeypatch):
    from onep.web import runtime
    root = tmp_path / "managed" / "projects"
    root.mkdir(parents=True)
    monkeypatch.setattr(runtime, "managed_root", lambda: root)
    for name in ["..", "../evil", "../../../../tmp/evil"]:
        with pytest.raises(ValueError):
            runtime.workspace_for(name)
    assert runtime.workspace_for("ok-name") == (root / "ok-name").resolve()


def test_create_project_catches_workspace_escape_as_400(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)

    def _raise(name):
        raise ValueError("escapes managed root")

    monkeypatch.setattr("onep.web.runtime.workspace_for", _raise)
    client = TestClient(create_app())
    response = client.post("/api/projects",
                           json={"requirement": "x", "name": "valid-name"})
    assert response.status_code == 400
    assert response.json()["detail"] == "escapes managed root"


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


def test_projects_list_initializes_db_on_fresh_home(tmp_path, monkeypatch):
    # Fresh home dir with NO meta.db; the list endpoint must not 500.
    home = tmp_path / "fresh-home"
    home.mkdir()
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: home)
    monkeypatch.setattr("onep.web.runtime.web_config", lambda: ("127.0.0.1", 8311))
    client = TestClient(create_app())
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json()["projects"] == []


def test_spawn_run_closes_log_handle(tmp_path, monkeypatch):
    from onep.web.runtime import spawn_run

    captured = {}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        @property
        def pid(self):
            return 1234

    monkeypatch.setattr("onep.web.runtime.subprocess.Popen", FakePopen)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = spawn_run("demo", workspace)
    assert result == {"pid": 1234, "started": True}
    assert captured["kwargs"]["stdout"].closed is True
