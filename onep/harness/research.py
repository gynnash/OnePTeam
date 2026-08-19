"""RESEARCH stage: open-source architecture research with degradation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.github_client import GitHubSearchClient
from onep.harness.research_models import (
    ArchitectureCard,
    EvidenceCard,
    ResearchReport,
    TradeoffRow,
    save_research_report,
)

RESEARCH_SYSTEM = (
    "You are the architecture researcher for an autonomous development "
    "harness. Ground every card in the provided repository evidence. "
    "Return JSON only."
)

QUESTIONS_PROMPT = """Produce focused architecture research questions for:
Goal: {goal}

Acceptance summary:
{acceptance}

Draft architecture:
{architecture}

Return JSON only: {{"questions": ["question 1", "question 2"]}}
At most 3 questions, each targeting a single architectural concern
(pattern, module boundaries, data flow, or scheduling)."""

CARDS_PROMPT = """Extract an architecture card per repository from this evidence.

Repositories:
{repos}

Return JSON only:
{{"cards": [{{"repo": "owner/name", "pattern": "...",
"module_boundaries": ["..."], "data_flow": "...",
"evidence_files": ["path/in/repo"], "strengths": ["..."],
"weaknesses": ["..."]}}]}}
Only include repositories whose evidence supports the card.
Evidence files MUST be real paths present in the repository listing."""

SYNTHESIS_PROMPT = """Synthesize the architecture cards into transferable
evidence and an explicit tradeoff matrix for our project.

Goal: {goal}
Cards:
{cards}

Return JSON only:
{{"evidence": [{{"claim": "...", "source_repos": ["owner/name"],
"detail": "..."}}],
"tradeoffs": [{{"option": "...", "decision": "adopt|reject|consider",
"reason": "...", "source_repos": ["owner/name"]}}]}}"""

LIGHTWEIGHT_PROMPT = """Reflect on the in-repo architecture and produce
transferable evidence only (no external search in this round).

Goal: {goal}
Acceptance summary:
{acceptance}

Draft architecture:
{architecture}

Return JSON only:
{{"evidence": [{{"claim": "...", "source_repos": [], "detail": "..."}}],
"tradeoffs": [{{"option": "...", "decision": "adopt|reject|consider",
"reason": "...", "source_repos": []}}]}}
The DESIGN stage will cite this in-repository evidence as source_repo="local"."""


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value]


class ResearchStage:
    """Full mode: questions -> GitHub search -> cards -> synthesis.
    Lightweight mode: one in-repo evidence call, no network.
    Any failure degrades to a skipped report (never raises)."""

    def __init__(
        self,
        llm,
        client: GitHubSearchClient | None = None,
        track: Callable[[Any, str], None] | None = None,
        max_questions: int = 2,
        max_repos: int = 3,
    ) -> None:
        self.llm = llm
        self.client = client or GitHubSearchClient()
        self.track = track
        self.max_questions = max_questions
        self.max_repos = max_repos
        self._last_mode = "auto"

    def _resolve_mode(self, mode: str, iteration: int) -> str:
        if mode == "auto":
            self._last_mode = "full" if iteration == 1 else "lightweight"
        else:
            self._last_mode = mode
        return self._last_mode

    def run(
        self,
        goal: str,
        acceptance_summary: str,
        architecture_summary: str,
        iteration: int,
        run_dir: Path,
        tracker=None,
        mode: str = "auto",
    ) -> ResearchReport:
        resolved = self._resolve_mode(mode, iteration)
        try:
            if resolved == "full":
                report = self._full(goal, acceptance_summary, architecture_summary)
            else:
                report = self._lightweight(
                    goal, acceptance_summary, architecture_summary
                )
        except Exception as exc:  # degradation: research never kills the run
            report = ResearchReport(
                mode="skipped",
                skip_reason=f"{type(exc).__name__}: {exc}",
            )
        save_research_report(run_dir, report)
        if self.track is not None and tracker is not None:
            self.track(tracker, "harness_researcher")
        return report

    def _full(
        self, goal: str, acceptance_summary: str, architecture_summary: str
    ) -> ResearchReport:
        output = self.llm.invoke(
            system_prompt=RESEARCH_SYSTEM,
            user_prompt=QUESTIONS_PROMPT.format(
                goal=goal or "(pure code optimization)",
                acceptance=acceptance_summary or "(none)",
                architecture=architecture_summary or "(none)",
            ),
            stage_name="harness_researcher",
        )
        questions = _str_list(_json_object(output or "").get("questions"))
        questions = [q for q in questions if q.strip()][: self.max_questions]
        if not questions:
            return ResearchReport(mode="skipped", skip_reason="no_research_questions")
        repos = []
        for question in questions:
            repos.extend(self.client.search_repos(question))
        repos = self.client.filter_repos(repos, max_repos=self.max_repos)
        if not repos:
            return ResearchReport(
                mode="skipped", skip_reason="no_matching_repositories"
            )
        cards = self._extract_cards(questions, repos)
        if cards is None:
            return ResearchReport(mode="skipped", skip_reason="readme_fetch_failed")
        if not cards:
            return ResearchReport(mode="skipped", skip_reason="no_architecture_cards")
        synthesis = self.llm.invoke(
            system_prompt=RESEARCH_SYSTEM,
            user_prompt=SYNTHESIS_PROMPT.format(
                goal=goal or "(pure code optimization)",
                cards=self._render_cards(cards),
            ),
            stage_name="harness_researcher",
        )
        data = _json_object(synthesis or "")
        researched = {card.repo.lower() for card in cards if card.repo}
        evidence = [
            EvidenceCard(
                claim=str(entry.get("claim") or ""),
                source_repos=[
                    repo
                    for repo in _str_list(entry.get("source_repos"))
                    if repo.lower() in researched
                ],
                detail=str(entry.get("detail") or ""),
            )
            for entry in data.get("evidence") or []
            if isinstance(entry, dict) and entry.get("claim")
        ]
        tradeoffs = [
            TradeoffRow(
                option=str(entry.get("option") or ""),
                decision=str(entry.get("decision") or ""),
                reason=str(entry.get("reason") or ""),
                source_repos=[
                    repo
                    for repo in _str_list(entry.get("source_repos"))
                    if repo.lower() in researched
                ],
            )
            for entry in data.get("tradeoffs") or []
            if isinstance(entry, dict) and entry.get("option")
        ]
        return ResearchReport(
            questions=questions,
            cards=cards,
            evidence=evidence,
            tradeoffs=tradeoffs,
            mode="full",
        )

    def _extract_cards(self, questions, repos) -> list[ArchitectureCard] | None:
        listings = []
        repositories = {repo.full_name.lower(): repo for repo in repos}
        for repo in repos:
            try:
                readme = self.client.fetch_readme(repo.full_name)
            except Exception:
                continue  # one repo failure must not stop the others
            tree = []
            try:
                tree = self.client.fetch_top_tree(repo.full_name)
            except Exception:
                pass
            source_files = {}
            fetch_file = getattr(self.client, "fetch_file", None)
            if fetch_file is not None:
                likely_sources = [
                    path
                    for path in tree
                    if Path(path).suffix.lower()
                    in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"}
                ][:5]
                for path in likely_sources:
                    try:
                        source_files[path] = fetch_file(repo.full_name, path)
                    except Exception:
                        continue
            listings.append(
                {
                    "full_name": repo.full_name,
                    "stars": repo.stargazers_count,
                    "language": repo.language,
                    "description": repo.description,
                    "tree": tree,
                    "readme": readme,
                    "source_files": source_files,
                }
            )
        if not listings:
            return None  # every README fetch failed
        output = self.llm.invoke(
            system_prompt=RESEARCH_SYSTEM,
            user_prompt=CARDS_PROMPT.format(repos=self._render_listings(listings)),
            stage_name="harness_researcher",
        )
        data = _json_object(output or "")
        cards = []
        for entry in data.get("cards") or []:
            if not isinstance(entry, dict) or not entry.get("repo"):
                continue
            repo_name = str(entry["repo"])
            repo = repositories.get(repo_name.lower())
            listing = next(
                (
                    value
                    for value in listings
                    if str(value.get("full_name") or "").lower() == repo_name.lower()
                ),
                None,
            )
            if repo is None or listing is None:
                continue
            known_paths = {str(path) for path in listing.get("tree") or []}
            grounded_paths = {str(path) for path in (listing.get("source_files") or {})}
            if listing.get("readme"):
                known_paths.add("README.md")
                grounded_paths.add("README.md")
            allowed_paths = grounded_paths or known_paths
            evidence_files = [
                path
                for path in _str_list(entry.get("evidence_files"))
                if path in allowed_paths
            ]
            if allowed_paths and not evidence_files:
                continue
            cards.append(
                ArchitectureCard(
                    repo=repo.full_name,
                    stars=repo.stargazers_count,
                    language=repo.language,
                    pattern=str(entry.get("pattern") or ""),
                    module_boundaries=_str_list(entry.get("module_boundaries")),
                    data_flow=str(entry.get("data_flow") or ""),
                    evidence_files=evidence_files,
                    strengths=_str_list(entry.get("strengths")),
                    weaknesses=_str_list(entry.get("weaknesses")),
                )
            )
        return cards

    def _lightweight(
        self, goal: str, acceptance_summary: str, architecture_summary: str
    ) -> ResearchReport:
        output = self.llm.invoke(
            system_prompt=RESEARCH_SYSTEM,
            user_prompt=LIGHTWEIGHT_PROMPT.format(
                goal=goal or "(pure code optimization)",
                acceptance=acceptance_summary or "(none)",
                architecture=architecture_summary or "(none)",
            ),
            stage_name="harness_researcher",
        )
        data = _json_object(output or "")
        evidence = [
            EvidenceCard(
                claim=str(entry.get("claim") or ""),
                source_repos=[],  # lightweight mode researched no repos
                detail=str(entry.get("detail") or ""),
            )
            for entry in data.get("evidence") or []
            if isinstance(entry, dict) and entry.get("claim")
        ]
        if not evidence:
            return ResearchReport(mode="skipped", skip_reason="lightweight_no_evidence")
        return ResearchReport(evidence=evidence, mode="lightweight")

    @staticmethod
    def _render_listings(listings: list[dict]) -> str:
        import json

        return json.dumps(listings, ensure_ascii=False, indent=2)

    @staticmethod
    def _render_cards(cards: list[ArchitectureCard]) -> str:
        import json

        return json.dumps(
            [card.to_dict() for card in cards], ensure_ascii=False, indent=2
        )
