# tests/test_harness/test_research_models.py
from pathlib import Path

from onep.harness.research_models import (
    ArchitectureCard,
    EvidenceCard,
    ResearchReport,
    TradeoffRow,
    load_research_reports,
    save_research_report,
)


def _report():
    return ResearchReport(
        questions=["How do mature CLIs structure orchestration?"],
        cards=[
            ArchitectureCard(
                repo="clap-rs/clap",
                stars=15200,
                language="Rust",
                pattern="derive-based declarative builder",
                module_boundaries=["parser", "builder", "errors"],
                data_flow="args -> parse -> matches",
                evidence_files=["src/parse.rs"],
                strengths=["composable"],
                weaknesses=["compile times"],
            )
        ],
        evidence=[EvidenceCard(
            claim="Declarative builders beat imperative wiring",
            source_repos=["clap-rs/clap"],
            detail="configuration is data",
        )],
        tradeoffs=[TradeoffRow(
            option="adopt builder pattern",
            decision="adopt",
            reason="evidence matches our scale",
            source_repos=["clap-rs/clap"],
        )],
        mode="full",
    )


def test_report_round_trip():
    report = _report()
    data = report.to_dict()
    restored = ResearchReport.from_dict(data)
    assert restored.questions == report.questions
    assert restored.cards[0].repo == "clap-rs/clap"
    assert restored.cards[0].stars == 15200
    assert restored.cards[0].module_boundaries == ["parser", "builder", "errors"]
    assert restored.evidence[0].claim == report.evidence[0].claim
    assert restored.tradeoffs[0].decision == "adopt"
    assert restored.mode == "full"


def test_report_repo_names_and_has_evidence():
    report = _report()
    assert report.repo_names == {"clap-rs/clap"}
    assert report.has_evidence is True
    skipped = ResearchReport(mode="skipped", skip_reason="no repos")
    assert skipped.has_evidence is False
    assert skipped.repo_names == set()


def test_report_from_dict_tolerates_missing_fields():
    restored = ResearchReport.from_dict({"mode": "full"})
    assert restored.questions == []
    assert restored.cards == []
    assert restored.evidence == []
    assert restored.tradeoffs == []
    assert restored.created_at == ""


def test_save_and_load_reports(tmp_path):
    run_dir = tmp_path / "runs" / "r-1"
    first = _report()
    second = ResearchReport(mode="skipped", skip_reason="rate limited")
    path1 = save_research_report(run_dir, first)
    path2 = save_research_report(run_dir, second)
    assert path1 == path2 == run_dir / "research-reports.jsonl"
    loaded = load_research_reports(run_dir)
    assert [r.mode for r in loaded] == ["full", "skipped"]
    assert loaded[0].cards[0].repo == "clap-rs/clap"
    assert loaded[1].skip_reason == "rate limited"


def test_load_research_reports_missing_dir_returns_empty(tmp_path):
    assert load_research_reports(tmp_path / "nope") == []
