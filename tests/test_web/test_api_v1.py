from fastapi.testclient import TestClient

from onep.application.defaults import build_application
from onep.web.server import create_app
from tests.test_web.fixtures import seed_project


def client(tmp_path):
    return TestClient(create_app(build_application(tmp_path / "control.db")))


def test_capabilities_expose_shared_actions(tmp_path):
    response = client(tmp_path).get("/api/v1/capabilities")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["capabilities"]}
    assert {"project.create", "run.start", "artifact.read", "memory.search"} <= ids


def test_background_action_is_idempotent_and_job_reports_result(tmp_path):
    app = build_application(tmp_path / "control.db")
    web = TestClient(create_app(app))
    headers = {"X-Action-ID": "same-request"}
    payload = {"project_id": "project-1"}

    first = web.post("/api/v1/actions/article.generate", json=payload, headers=headers)
    second = web.post("/api/v1/actions/article.generate", json=payload, headers=headers)

    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    job = web.get(f"/api/v1/jobs/{first.json()['job_id']}").json()
    assert job["status"] == "queued"
    assert job["result"] == {}


def test_artifact_read_uses_project_id_and_rejects_unknown_artifact(
    tmp_path, monkeypatch
):
    workspace = seed_project(tmp_path, monkeypatch, name="same-name")
    (workspace / "docs").mkdir(exist_ok=True)
    (workspace / "docs" / "PRD.md").write_text("# Goal", encoding="utf-8")
    project_id = client(tmp_path).get("/api/v1/projects").json()["projects"][0]["id"]
    web = client(tmp_path)

    response = web.post(
        "/api/v1/actions/artifact.read",
        json={"project_id": project_id, "artifact": "prd"},
    )
    missing = web.post(
        "/api/v1/actions/artifact.read",
        json={"project_id": project_id, "artifact": "../../secret"},
    )

    assert response.status_code == 202
    assert response.json()["data"]["content"] == "# Goal"
    assert missing.status_code == 404


def test_v1_workbench_reads_project_by_id(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")
    web = client(tmp_path)
    project = web.get("/api/v1/projects").json()["projects"][0]

    detail = web.get(f"/api/v1/projects/{project['id']}")
    logs = web.get(f"/api/v1/projects/{project['id']}/log")
    candidates = web.get(f"/api/v1/projects/{project['id']}/candidates")
    knowledge = web.get(f"/api/v1/projects/{project['id']}/knowledge")

    assert detail.status_code == 200
    assert detail.json()["run"]["stop_state"]["reason"] == "goals_satisfied"
    assert logs.status_code == candidates.status_code == knowledge.status_code == 200
