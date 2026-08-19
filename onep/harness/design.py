"""DESIGN stage: architecture generation with research evidence citations."""

from __future__ import annotations

from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.research_models import ResearchReport

DESIGN_SYSTEM = (
    "You are the architect for an autonomous development harness. "
    "You MUST cite research evidence for every architectural decision. "
    "Return JSON only."
)

DESIGN_PROMPT = """Finalize the architecture for this build round.

Acceptance summary:
{acceptance}

Research evidence (cite these repos only):
{evidence}

Draft architecture:
{draft}

Return JSON only:
{{"architecture": {{...complete architecture object...}},
"evidence_citations": [
  {{"claim": "what we adopt or reject and why",
    "source_repo": "owner/name from the research above",
    "detail": "how the evidence applies to us"}}
]}}
Every citation's source_repo MUST come from the research evidence above. For
lightweight in-repository evidence whose source_repos is empty, use
source_repo="local"."""


def _researched_repo_names(report: ResearchReport) -> set[str]:
    """Researched repos = architecture cards plus repos cited in evidence."""
    names = set(report.repo_names)
    for evidence in report.evidence:
        for repo in evidence.source_repos or []:
            if repo:
                names.add(str(repo).lower())
    if report.evidence and not names:
        names.add("local")
    return names


class DesignStage:
    """Architect with mandatory evidence citations; invalid citations are
    dropped with recorded warnings instead of failing the run."""

    def __init__(
        self,
        llm,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.track = track

    def run(
        self,
        report: ResearchReport,
        contract_summary: str,
        draft_architecture: dict[str, Any],
        iteration: int,
        tracker=None,
    ) -> tuple[dict[str, Any], list[str]]:
        if not report.has_evidence:
            return draft_architecture, []
        import json

        try:
            output = self.llm.invoke(
                system_prompt=DESIGN_SYSTEM,
                user_prompt=DESIGN_PROMPT.format(
                    acceptance=contract_summary or "(none)",
                    evidence=json.dumps(
                        [card.to_dict() for card in report.evidence],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    draft=json.dumps(draft_architecture, ensure_ascii=False),
                ),
                stage_name="harness_architect",
            )
        except Exception:
            if self.track is not None and tracker is not None:
                self.track(tracker, "harness_architect")
            return draft_architecture, ["architect unavailable; retained draft"]
        if self.track is not None and tracker is not None:
            self.track(tracker, "harness_architect")
        data = _json_object(output or "")
        architecture = data.get("architecture")
        if not isinstance(architecture, dict):
            return draft_architecture, []
        citations = data.get("evidence_citations") or []
        valid, warnings = self.validate_citations(
            citations,
            _researched_repo_names(report),
            {card.claim.strip().casefold() for card in report.evidence if card.claim},
        )
        if not valid:
            warnings.append(
                "architecture had no valid evidence citation; retained draft"
            )
            return draft_architecture, warnings
        architecture["evidence_citations"] = valid
        return architecture, warnings

    @staticmethod
    def validate_citations(
        citations: Any,
        repo_names: set[str],
        evidence_claims: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(citations, list):
            return [], ["evidence_citations is not a list"]
        valid: list[dict[str, Any]] = []
        warnings: list[str] = []
        for citation in citations:
            if not isinstance(citation, dict):
                warnings.append("non-object citation dropped")
                continue
            repo = str(citation.get("source_repo") or "")
            if repo.lower() not in repo_names:
                warnings.append(f"citation for unresearched repo dropped: {repo}")
                continue
            claim = str(citation.get("claim") or "").strip()
            if evidence_claims is not None and claim.casefold() not in evidence_claims:
                warnings.append(
                    f"citation without matching evidence claim dropped: {claim}"
                )
                continue
            valid.append(citation)
        return valid, warnings
