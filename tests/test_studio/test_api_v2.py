from fastapi.testclient import TestClient

from onep.application.studio_defaults import build_application
from onep.studio.articles import ArticleStudio
from onep.studio.credentials import MemoryCredentialStore
from onep.studio.knowledge import KnowledgeService
from onep.studio.service import StudioService
from onep.studio.store import StudioStore
from onep.web.server import create_app

from .test_product_studio import FakeProductModel


def test_v2_is_the_only_mounted_product_api(tmp_path):
    studio = StudioService(
        StudioStore(tmp_path / "studio.db"), product_model=FakeProductModel()
    )
    application = build_application(tmp_path / "control.db")
    client = TestClient(create_app(application, studio))

    created = client.post(
        "/api/v2/projects",
        json={"idea": "一句话产品", "repo": str(tmp_path / "repo")},
        headers={"X-Action-ID": "create-api"},
    )
    assert created.status_code == 201
    project_id = created.json()["project"]["id"]
    replay = client.post(
        "/api/v2/projects",
        json={"idea": "不同内容不会重复创建"},
        headers={"X-Action-ID": "create-api"},
    )
    assert replay.json()["project"]["id"] == project_id
    assert len(client.get("/api/v2/projects").json()["projects"]) == 1
    snapshot = client.get(f"/api/v2/projects/{project_id}/studio")
    assert snapshot.status_code == 200
    assert snapshot.json()["project"]["state"] == "discovery"

    assert client.get("/api/v1/projects").status_code == 404

    deep_link = client.get(f"/projects/{project_id}")
    assert deep_link.status_code == 200
    assert '<div id="root"></div>' in deep_link.text


def test_article_model_api_never_returns_plaintext_credentials(tmp_path):
    store = StudioStore(tmp_path / "studio.db")
    studio = StudioService(
        store,
        articles=ArticleStudio(
            store, KnowledgeService(store), credentials=MemoryCredentialStore()
        ),
    )
    application = build_application(tmp_path / "control.db")
    client = TestClient(create_app(application, studio))

    headers = {"X-Action-ID": "article-model-create"}
    response = client.post(
        "/api/v2/settings/article-models",
        headers=headers,
        json={
            "name": "文章模型",
            "provider": "openai",
            "model": "test",
            "credential": "sk-plain-secret-value",
            "is_default": True,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["credential_configured"] is True
    assert payload["credential_source"] == "os_keyring"
    assert "credential_ref" not in payload
    assert "sk-plain-secret-value" not in response.text

    replay = client.post(
        "/api/v2/settings/article-models",
        headers=headers,
        json={
            "name": "不会重复创建",
            "provider": "other",
            "model": "other",
            "credential": "another-secret",
        },
    )
    assert replay.json()["id"] == payload["id"]
    assert len(client.get("/api/v2/settings/article-models").json()["profiles"]) == 1

    listed = client.get("/api/v2/settings/article-models")
    assert "sk-plain-secret-value" not in listed.text


def test_adaptive_discovery_and_prd_review_routes(tmp_path):
    studio = StudioService(
        StudioStore(tmp_path / "studio.db"), product_model=FakeProductModel()
    )
    client = TestClient(create_app(build_application(tmp_path / "control.db"), studio))
    created = client.post(
        "/api/v2/projects",
        json={"idea": "通过 API 澄清产品"},
        headers={"X-Action-ID": "create-discovery"},
    ).json()
    project_id = created["project"]["id"]

    discovery = client.get(f"/api/v2/projects/{project_id}/discovery")
    assert discovery.status_code == 200
    assert discovery.json()["session"]["current_round"] == 1
    assert client.get("/api/v2/projects/missing/discovery").status_code == 404
    premature = client.post(
        f"/api/v2/projects/{project_id}/discovery/decision",
        json={"action": "draft_with_assumptions"},
        headers={"X-Action-ID": "premature-decision"},
    )
    assert premature.status_code == 409
    assert premature.json()["code"] == "discovery_decision_not_available"

    reviewed = client.post(
        f"/api/v2/projects/{project_id}/discovery/answers",
        json={
            "answers": [
                {"question_id": question["id"], "answer": "用户确认"}
                for question in created["questions"]
            ]
        },
        headers={"X-Action-ID": "answer-discovery"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["project"]["state"] == "prd_review"
    version = reviewed.json()["prd"]["version"]

    revalidated = client.post(
        f"/api/v2/projects/{project_id}/prd/{version}/revalidate",
        headers={"X-Action-ID": "revalidate-prd"},
    )
    assert revalidated.status_code == 200
    assert revalidated.json()["passed"] is True
    legacy = client.post(f"/api/v2/projects/{project_id}/answers")
    assert legacy.status_code == 409
    assert legacy.json()["code"] == "invalid_project_action"


def test_resume_requeues_the_approved_release_idempotently(tmp_path):
    studio = StudioService(
        StudioStore(tmp_path / "studio.db"), product_model=FakeProductModel()
    )
    application = build_application(tmp_path / "control.db")
    created = studio.create_project(
        {"idea": "可暂停交付", "repo": str(tmp_path / "repo")}
    )
    project_id = created["project"]["id"]
    reviewed = studio.answer_discovery(
        project_id,
        {
            "answers": [
                {"question_id": question["id"], "answer": "确认"}
                for question in created["questions"]
            ]
        },
    )
    studio.approve_prd(project_id, reviewed["prd"]["version"], {})
    studio.store.update_project(project_id, state="paused")
    client = TestClient(create_app(application, studio))
    headers = {"X-Action-ID": "resume-once"}

    resumed = client.post(f"/api/v2/projects/{project_id}/resume", headers=headers)
    replay = client.post(f"/api/v2/projects/{project_id}/resume", headers=headers)

    assert resumed.status_code == 200
    assert resumed.json()["project"]["state"] == "ready"
    assert resumed.json()["execution"]["job_id"]
    assert replay.json()["execution"]["job_id"] == resumed.json()["execution"]["job_id"]
    assert len(application.store.jobs()) == 1
