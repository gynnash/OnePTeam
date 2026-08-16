import json
from pathlib import Path

import git

from onep.harness.article import ArticleSynthesizer
from onep.harness.knowledge_models import KnowledgeEvent, save_distillations
from onep.harness.models import HarnessRun, QualitySnapshot
from onep.harness.vault import VaultWriter


class ArticleLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        return self.responses.pop(0) if self.responses else "{}"


def _article_fixture(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    repo = git.Repo.init(workspace)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (workspace / "app.py").write_text("VALUE = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("feat: core value")
    run = HarnessRun(
        id="h-1", project_name="demo", workspace=str(workspace),
        mode="greenfield", original_goal="build value",
        quality_history=[QualitySnapshot(
            iteration=1, acceptance_pass_rate=1.0, test_pass_rate=1.0,
            goal_coverage=1.0, quality_score=1.0, hard_gates_passed=True,
        )],
        stop_state={"reason": "goals_satisfied", "evidence": {}},
        knowledge_events=[{
            "type": "decision", "iteration": 1, "problem": "how to wire",
            "selected": "flat", "reason": "simpler", "generalizable": False,
        }],
    )
    run_dir = tmp_path / "runs" / "h-1"
    run_dir.mkdir(parents=True)
    save_distillations(run_dir, [
        KnowledgeEvent(type="decision", iteration=1, problem="how to wire",
                       selected="flat", reason="simpler"),
        KnowledgeEvent(type="failure", iteration=1, problem="gate failed",
                       outcome="repaired"),
    ])
    with open(run_dir / "events.jsonl", "a") as handle:
        handle.write(json.dumps({
            "type": "repair_brief", "payload": {"failure_type": "test_failed"},
        }) + "\n")
    with open(run_dir / "architecture-decisions.jsonl", "a") as handle:
        handle.write(json.dumps({"architecture": {"selected": "flat"}}) + "\n")
    return workspace, run_dir, run


def test_synthesize_writes_article_and_graph(tmp_path):
    workspace, run_dir, run = _article_fixture(tmp_path)
    llm = ArticleLLM([
        '{"events": [{"id": "e1", "type": "decision", '
        '"problem": "how to wire", "selected": "flat", '
        '"reason": "simpler", "iteration": 1}]}',
        '{"clusters": [{"problem": "wiring", "event_ids": ["e1"], '
        '"resolution": "flat"}]}',
        '{"nodes": [{"id": "n1", "label": "wiring", "kind": "decision"}], '
        '"edges": []}',
        '{"insights": [{"title": "keep it flat", "summary": "flat wins", '
        '"evidence": "e1"}]}',
        '{"title": "Demo Journey", "markdown": "# Demo Journey\\n\\n'
        '## What We Initially Believed\\n\\nWe believed nested.\\n\\n'
        '## Decisions That Shaped the Outcome\\n\\n'
        'We adopted [[how-to-wire]].\\n"}',
    ])
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    synthesizer = ArticleSynthesizer(llm, writer)
    result = synthesizer.synthesize(workspace, run_dir, run)

    assert result["title"] == "Demo Journey"
    assert result["article_path"].exists()
    text = result["article_path"].read_text()
    assert "type: article" in text
    assert "[[how-to-wire]]" in text
    assert result["graph_path"].exists()
    assert result["graph"]["nodes"][0]["id"] == "n1"
    assert llm.calls == [
        "harness_article_extract", "harness_article_cluster",
        "harness_article_graph", "harness_article_insight",
        "harness_article_narrative",
    ]


def test_synthesize_no_events_skips_insight_llm(tmp_path):
    workspace, run_dir, run = _article_fixture(tmp_path)
    (run_dir / "distillations.jsonl").unlink()
    llm = ArticleLLM([
        '{"events": []}',
        '{"title": "Demo Journey", "markdown": "# Demo Journey\\n\\n'
        '## What We Initially Believed\\n\\nNothing recorded.\\n"}',
    ])
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    result = ArticleSynthesizer(llm, writer).synthesize(
        workspace, run_dir, run)
    assert result["article_path"].exists()
    assert "harness_article_insight" not in llm.calls
    assert llm.calls == [
        "harness_article_extract", "harness_article_narrative",
    ]


def test_synthesize_falls_back_to_timeline_on_garbage(tmp_path):
    workspace, run_dir, run = _article_fixture(tmp_path)
    llm = ArticleLLM(["not json"] * 5)
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    result = ArticleSynthesizer(llm, writer).synthesize(
        workspace, run_dir, run)
    assert result["article_path"].exists()
    assert "Timeline" in result["markdown"]
    assert "feat: core value" in result["markdown"]
    assert "goals_satisfied" in result["markdown"]


class RaisingNarrativeLLM(ArticleLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_article_narrative":
            raise RuntimeError("narrative boom")
        return super().invoke(system_prompt, user_prompt, stage_name)


def test_synthesize_falls_back_when_narrative_llm_raises(tmp_path):
    workspace, run_dir, run = _article_fixture(tmp_path)
    llm = RaisingNarrativeLLM([
        '{"events": [{"id": "e1", "type": "decision", '
        '"problem": "how to wire", "selected": "flat", '
        '"reason": "simpler", "iteration": 1}]}',
        '{"clusters": [{"problem": "wiring", "event_ids": ["e1"], '
        '"resolution": "flat"}]}',
        '{"nodes": [], "edges": []}',
        '{"insights": []}',
        "unused",
    ])
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    result = ArticleSynthesizer(llm, writer).synthesize(
        workspace, run_dir, run)
    assert result["article_path"].exists()
    text = result["article_path"].read_text()
    assert "goals_satisfied" in text
    assert "build value" in text
    assert "## Timeline (evidence)" in result["markdown"]
