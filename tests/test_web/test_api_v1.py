from fastapi.testclient import TestClient
import git

from onep.application.defaults import build_application
from onep.web.server import create_app
from tests.test_web.fixtures import seed_project


def client(tmp_path):
    return TestClient(create_app(build_application(tmp_path / "control.db")))


def test_capabilities_expose_shared_actions(tmp_path):
    response = client(tmp_path).get("/api/v1/capabilities")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["capabilities"]}
    assert {
        "project.create",
        "run.start",
        "artifact.read",
        "memory.search",
        "settings.global.read",
        "project.settings.update",
    } <= ids


def test_health_reports_worker_readiness(tmp_path):
    app = build_application(tmp_path / "control.db")
    web = TestClient(create_app(app))

    degraded = web.get("/api/v1/health")
    app.store.worker_heartbeat("worker-web")
    ready = web.get("/api/v1/health")

    assert degraded.json()["status"] == "degraded"
    assert ready.json()["status"] == "ready"
    assert ready.json()["worker"]["worker_id"] == "worker-web"


def test_directory_picker_returns_visual_selection_and_current_branch(
    tmp_path, monkeypatch
):
    repository_path = tmp_path / "picked-repository"
    repository_path.mkdir()
    repository = git.Repo.init(repository_path, initial_branch="feature/home")
    with repository.config_writer() as config:
        config.set_value("user", "name", "OneP Test")
        config.set_value("user", "email", "onep@example.com")
    (repository_path / "app.py").write_text("ready = True\n")
    repository.index.add(["app.py"])
    repository.index.commit("initial")
    monkeypatch.setattr(
        "onep.web.api_v1.pick_local_directory",
        lambda _initial: repository_path,
    )

    response = client(tmp_path).post(
        "/api/v1/system/pick-directory",
        json={"initial_path": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "path": str(repository_path),
        "branch": "feature/home",
        "cancelled": False,
    }


def test_directory_picker_preserves_form_when_user_cancels(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.web.api_v1.pick_local_directory", lambda _initial: None
    )

    response = client(tmp_path).post("/api/v1/system/pick-directory", json={})

    assert response.status_code == 200
    assert response.json() == {"path": "", "branch": "", "cancelled": True}


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
    assert detail.json()["mutations_supported"] is False
    assert logs.status_code == candidates.status_code == knowledge.status_code == 200


def test_project_settings_preserve_explicit_legacy_default_values(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="settings-demo")
    web = client(tmp_path)
    project = web.get("/api/v1/projects").json()["projects"][0]
    initial = web.get(f"/api/v1/projects/{project['id']}/settings").json()

    updated = web.patch(
        f"/api/v1/projects/{project['id']}/settings",
        json={
            "revision": initial["revision"],
            "patch": {
                "max_rounds": 12,
                "max_repairs_per_slice": 3,
                "test_commands": ["python -m pytest -q", "python -m pytest -q"],
            },
        },
    )

    assert updated.status_code == 200
    assert updated.json()["defaults"]["max_rounds"] == 12
    assert updated.json()["defaults"]["max_repairs_per_slice"] == 3
    assert updated.json()["defaults"]["test_commands"] == ["python -m pytest -q"]


def test_project_settings_reject_unsafe_test_command(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="unsafe-settings")
    web = client(tmp_path)
    project = web.get("/api/v1/projects").json()["projects"][0]

    response = web.patch(
        f"/api/v1/projects/{project['id']}/settings",
        json={"patch": {"test_commands": ["pytest -q && echo unsafe"]}},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_test_command"


def test_unified_task_routes_from_goal_and_repository_contents(tmp_path):
    repository = tmp_path / "target-repository"
    repository.mkdir()
    (repository / "service.py").write_text("def ready(): return True\n")

    response = client(tmp_path).post(
        "/api/v1/tasks",
        json={
            "goal": "分析服务的模块边界，不修改代码",
            "source": str(repository),
            "branch": "main",
        },
    )

    assert response.status_code == 202
    assert response.json()["workflow"] == "analyze"
    assert response.json()["repository"]["source"] == str(repository)
    assert response.json()["repository"]["branch"] == "main"
    job = client(tmp_path).get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert job["capability_id"] == "analysis.start"


def test_unified_task_requires_local_repository_for_mutation(tmp_path):
    response = client(tmp_path).post(
        "/api/v1/tasks",
        json={
            "goal": "优化缓存性能",
            "source": "https://example.com/team/repository.git",
            "branch": "main",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "local_repository_required"


def test_unified_task_requires_git_before_modifying_existing_local_code(tmp_path):
    repository = tmp_path / "plain-directory"
    repository.mkdir()
    (repository / "service.py").write_text("def ready(): return True\n")

    response = client(tmp_path).post(
        "/api/v1/tasks",
        json={
            "goal": "优化缓存性能",
            "source": str(repository),
            "branch": "main",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "git_repository_required"


def test_unified_optimization_accepts_dirty_repository(tmp_path):
    repository = tmp_path / "dirty-repository"
    repository.mkdir()
    repo = git.Repo.init(repository, initial_branch="main")
    (repository / "service.py").write_text("def ready(): return True\n")
    repo.index.add(["service.py"])
    repo.index.commit("initial")
    (repository / "notes.txt").write_text("not committed\n")
    web = client(tmp_path)

    response = web.post(
        "/api/v1/tasks",
        json={
            "goal": "优化缓存性能",
            "source": str(repository),
            "branch": "main",
        },
    )

    assert response.status_code == 202
    assert response.json()["workflow"] == "optimize"
    job = web.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert job["capability_id"] == "optimization.start"
