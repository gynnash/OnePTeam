from pathlib import Path

from fastapi.testclient import TestClient

from onep.harness.interventions import load_candidate_decisions
from onep.harness.models import HarnessRun, HarnessOptions, ImprovementCandidate
from onep.harness.persistence import load_harness_run, save_harness_run
from onep.web.server import create_app

from tests.test_web.fixtures import seed_project


def _seed_with_candidate(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    run = load_harness_run(workspace)
    run.improvement_candidates = [
        ImprovementCandidate(id="I-1", title="Add CLI", score=0.5, status="parked"),
    ]
    save_harness_run(run)
    return workspace


def test_candidates_list_merges_decisions(tmp_path, monkeypatch):
    _seed_with_candidate(tmp_path, monkeypatch)
    client = TestClient(create_app())
    response = client.get("/api/projects/demo/candidates")
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates[0]["id"] == "I-1"
    assert candidates[0]["decision"] is None


def test_approve_writes_decision(tmp_path, monkeypatch):
    workspace = _seed_with_candidate(tmp_path, monkeypatch)
    client = TestClient(create_app())
    response = client.post("/api/projects/demo/candidates/I-1/approve",
                           json={"note": "ship it"})
    assert response.status_code == 200
    entry = load_candidate_decisions(workspace)[0]
    assert entry["decision"] == "approve"
    assert entry["applied"] is False
    merged = client.get("/api/projects/demo/candidates").json()["candidates"]
    assert merged[0]["decision"]["decision"] == "approve"


def test_reject_and_rescore(tmp_path, monkeypatch):
    workspace = _seed_with_candidate(tmp_path, monkeypatch)
    client = TestClient(create_app())
    assert client.post("/api/projects/demo/candidates/I-1/reject", json={}).status_code == 200
    assert client.post("/api/projects/demo/candidates/I-1/rescore",
                       json={"score": 0.9}).status_code == 200
    entries = load_candidate_decisions(workspace)
    assert [entry["decision"] for entry in entries] == ["reject", "rescore"]
    assert client.post("/api/projects/demo/candidates/I-1/rescore",
                       json={}).status_code == 400


def test_unknown_candidate_404(tmp_path, monkeypatch):
    _seed_with_candidate(tmp_path, monkeypatch)
    client = TestClient(create_app())
    assert client.post("/api/projects/demo/candidates/NOPE/approve",
                       json={}).status_code == 404


def test_article_trigger(tmp_path, monkeypatch):
    seed_project(tmp_path, monkeypatch, name="demo")

    class FakeSynthesizer:
        def __init__(self, llm, writer):
            self.llm = llm
            self.writer = writer

        def synthesize(self, workspace, run_dir, run, tracker=None):
            return {"title": "Demo Journey",
                    "article_path": Path("/tmp/demo.md"),
                    "graph_path": Path("/tmp/demo.graph.json"),
                    "markdown": "# Demo", "graph": {"nodes": [], "edges": []}}

    monkeypatch.setattr("onep.web.api.projects.ArticleSynthesizer", FakeSynthesizer)
    monkeypatch.setattr("onep.web.api.projects.LLMAdapter", lambda: object())
    client = TestClient(create_app())
    response = client.post("/api/projects/demo/article")
    assert response.status_code == 200
    assert response.json()["title"] == "Demo Journey"
    assert client.post("/api/projects/missing/article").status_code == 404
