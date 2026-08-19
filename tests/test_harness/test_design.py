# tests/test_harness/test_design.py
from onep.harness.design import DesignStage
from onep.harness.research_models import EvidenceCard, ResearchReport


class DesignLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        return self.payload


def _report():
    return ResearchReport(
        cards=[],
        evidence=[EvidenceCard(claim="builders win", source_repos=["cli/repo"])],
        mode="full",
    )


PAYLOAD = (
    '{"architecture": {"selected": "builder", "rationale": "x"}, '
    '"evidence_citations": ['
    '{"claim": "builders win", "source_repo": "cli/repo", '
    '"detail": "adopt"},'
    '{"claim": "use rust", "source_repo": "ghost/repo", '
    '"detail": "reject"}]}'
)


def test_design_generates_architecture_with_valid_citations():
    llm = DesignLLM(PAYLOAD)
    architecture, warnings = DesignStage(llm).run(
        _report(),
        "- REQ-1 ok",
        {"selected": "draft"},
        1,
    )
    assert architecture["selected"] == "builder"
    citations = architecture["evidence_citations"]
    assert [c["source_repo"] for c in citations] == ["cli/repo"]
    assert llm.calls == ["harness_architect"]
    assert len(warnings) == 1
    assert "ghost/repo" in warnings[0]


def test_design_skips_llm_when_report_has_no_evidence():
    llm = DesignLLM(PAYLOAD)
    skipped = ResearchReport(mode="skipped", skip_reason="no repos")
    architecture, warnings = DesignStage(llm).run(
        skipped,
        "",
        {"selected": "draft"},
        1,
    )
    assert architecture == {"selected": "draft"}
    assert warnings == []
    assert llm.calls == []


def test_design_falls_back_to_draft_on_garbage():
    llm = DesignLLM("not json")
    architecture, warnings = DesignStage(llm).run(
        _report(),
        "",
        {"selected": "draft"},
        1,
    )
    assert architecture == {"selected": "draft"}
    assert warnings == []


def test_design_case_insensitive_repo_matching():
    llm = DesignLLM(
        '{"architecture": {}, "evidence_citations": ['
        '{"claim": "builders win", "source_repo": "CLI/REPO", "detail": "d"}]}'
    )
    architecture, warnings = DesignStage(llm).run(
        _report(),
        "",
        {"selected": "draft"},
        1,
    )
    assert [c["source_repo"] for c in architecture["evidence_citations"]] == (
        ["CLI/REPO"]
    )
    assert warnings == []


def test_validate_citations_drops_invalid_and_reports_warnings():
    citations = [
        {"claim": "a", "source_repo": "cli/repo"},
        {"claim": "b", "source_repo": "ghost/repo"},
        {"claim": "c"},  # no source_repo at all
    ]
    valid, warnings = DesignStage.validate_citations(citations, {"cli/repo"})
    assert valid == [{"claim": "a", "source_repo": "cli/repo"}]
    assert len(warnings) == 2


def test_design_rejects_uncited_architecture_when_evidence_exists():
    llm = DesignLLM(
        '{"architecture": {"selected": "invented"}, ' '"evidence_citations": []}'
    )
    architecture, warnings = DesignStage(llm).run(
        _report(),
        "",
        {"selected": "draft"},
        1,
    )
    assert architecture == {"selected": "draft"}
    assert any("no valid evidence citation" in warning for warning in warnings)


def test_design_accepts_local_lightweight_citation():
    report = ResearchReport(
        evidence=[EvidenceCard(claim="keep modules flat", source_repos=[])],
        mode="lightweight",
    )
    llm = DesignLLM(
        '{"architecture": {"selected": "flat"}, "evidence_citations": ['
        '{"claim": "keep modules flat", "source_repo": "local", '
        '"detail": "matches current repository"}]}'
    )
    architecture, warnings = DesignStage(llm).run(
        report,
        "",
        {"selected": "draft"},
        2,
    )
    assert architecture["selected"] == "flat"
    assert warnings == []
