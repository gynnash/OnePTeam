from fastapi.testclient import TestClient

from onep.web.server import create_app

from tests.test_web.fixtures import seed_project, seed_vault


def _vaulted_client(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    seed_vault(workspace, tmp_path, monkeypatch)
    return TestClient(create_app())


def test_notes_list_project(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    response = client.get("/api/knowledge/notes?vault=project&project=demo")
    assert response.status_code == 200
    notes = response.json()["notes"]
    assert any(note["path"].startswith("Experiments/") for note in notes)


def test_notes_list_requires_project_for_project_vault(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    assert client.get("/api/knowledge/notes?vault=project").status_code == 400
    assert client.get("/api/knowledge/notes?vault=nope").status_code == 422


def test_notes_list_global_without_project(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    response = client.get("/api/knowledge/notes?vault=global")
    assert response.status_code == 200
    assert any(note["slug"] == "demo" for note in response.json()["notes"])


def test_note_content(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    notes = client.get("/api/knowledge/notes?vault=project&project=demo").json()["notes"]
    event_note = next(n for n in notes if n["path"].startswith("Experiments/"))
    response = client.get(
        f"/api/knowledge/notes/content?vault=project&project=demo&path={event_note['path']}")
    assert response.status_code == 200
    assert "all tests pass" in response.json()["body"]
    traversal = client.get(
        "/api/knowledge/notes/content?vault=project&project=demo&path=../run.yaml")
    assert traversal.status_code == 404


def test_graph(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    response = client.get("/api/knowledge/graph?project=demo")
    assert response.status_code == 200
    assert response.json()["nodes"]


def test_articles(tmp_path, monkeypatch):
    client = _vaulted_client(tmp_path, monkeypatch)
    response = client.get("/api/knowledge/articles")
    assert response.status_code == 200
    assert response.json()["articles"][0]["slug"] == "demo"
    content = client.get("/api/knowledge/articles/demo")
    assert content.status_code == 200
    assert content.json()["title"] == "Demo Journey"
    assert client.get("/api/knowledge/articles/missing").status_code == 404
