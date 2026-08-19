"""Research stage data models: architecture cards, evidence, tradeoffs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value]


@dataclass
class ArchitectureCard:
    repo: str
    stars: int = 0
    language: str = ""
    pattern: str = ""
    module_boundaries: list[str] = field(default_factory=list)
    data_flow: str = ""
    evidence_files: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "stars": self.stars,
            "language": self.language,
            "pattern": self.pattern,
            "module_boundaries": list(self.module_boundaries),
            "data_flow": self.data_flow,
            "evidence_files": list(self.evidence_files),
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchitectureCard":
        return cls(
            repo=str(data.get("repo") or ""),
            stars=int(data.get("stars") or 0),
            language=str(data.get("language") or ""),
            pattern=str(data.get("pattern") or ""),
            module_boundaries=_str_list(data.get("module_boundaries")),
            data_flow=str(data.get("data_flow") or ""),
            evidence_files=_str_list(data.get("evidence_files")),
            strengths=_str_list(data.get("strengths")),
            weaknesses=_str_list(data.get("weaknesses")),
        )


@dataclass
class EvidenceCard:
    claim: str
    source_repos: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "source_repos": list(self.source_repos),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceCard":
        return cls(
            claim=str(data.get("claim") or ""),
            source_repos=_str_list(data.get("source_repos")),
            detail=str(data.get("detail") or ""),
        )


@dataclass
class TradeoffRow:
    option: str
    decision: str = ""
    reason: str = ""
    source_repos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "option": self.option,
            "decision": self.decision,
            "reason": self.reason,
            "source_repos": list(self.source_repos),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradeoffRow":
        return cls(
            option=str(data.get("option") or ""),
            decision=str(data.get("decision") or ""),
            reason=str(data.get("reason") or ""),
            source_repos=_str_list(data.get("source_repos")),
        )


@dataclass
class ResearchReport:
    questions: list[str] = field(default_factory=list)
    cards: list[ArchitectureCard] = field(default_factory=list)
    evidence: list[EvidenceCard] = field(default_factory=list)
    tradeoffs: list[TradeoffRow] = field(default_factory=list)
    mode: str = "skipped"  # full | lightweight | skipped
    skip_reason: str = ""
    created_at: str = field(default_factory=_now)

    @property
    def repo_names(self) -> set[str]:
        return {card.repo.lower() for card in self.cards if card.repo}

    @property
    def has_evidence(self) -> bool:
        return self.mode != "skipped" and bool(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "questions": list(self.questions),
            "cards": [card.to_dict() for card in self.cards],
            "evidence": [card.to_dict() for card in self.evidence],
            "tradeoffs": [row.to_dict() for row in self.tradeoffs],
            "mode": self.mode,
            "skip_reason": self.skip_reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchReport":
        return cls(
            questions=_str_list(data.get("questions")),
            cards=[
                ArchitectureCard.from_dict(entry)
                for entry in data.get("cards") or []
                if isinstance(entry, dict)
            ],
            evidence=[
                EvidenceCard.from_dict(entry)
                for entry in data.get("evidence") or []
                if isinstance(entry, dict)
            ],
            tradeoffs=[
                TradeoffRow.from_dict(entry)
                for entry in data.get("tradeoffs") or []
                if isinstance(entry, dict)
            ],
            mode=str(data.get("mode") or "skipped"),
            skip_reason=str(data.get("skip_reason") or ""),
            created_at=str(data.get("created_at") or ""),
        )


def research_reports_path(run_dir: Path) -> Path:
    return Path(run_dir) / "research-reports.jsonl"


def save_research_report(run_dir: Path, report: ResearchReport) -> Path:
    path = research_reports_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        handle.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        handle.flush()
    return path


def load_research_reports(run_dir: Path) -> list[ResearchReport]:
    path = research_reports_path(run_dir)
    if not path.exists():
        return []
    reports = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            reports.append(ResearchReport.from_dict(raw))
    return reports
