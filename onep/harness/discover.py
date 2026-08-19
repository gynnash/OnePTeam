# onep/harness/discover.py
"""DISCOVER and PRIORITIZE stages of the Product Loop."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from onep.harness.models import ImprovementCandidate
from onep.strategy.optimize_models import PlanCandidate
from onep.strategy.plan_scheduler import PlanScheduler


BRAINSTORM_SYSTEM = (
    "You are the Product Reflector for an autonomous development harness. "
    "Ground every proposal in the delivered product and its acceptance "
    "evidence. Return JSON only."
)

BRAINSTORM_PROMPT = """Propose concrete improvements to the product built so far.

Original goal: {goal}

Delivered acceptance items:
{acceptance}

Code quality signals (tests, review findings, lint):
{code_signals}

Prior improvement candidates (do not repeat these):
{prior}

Quality snapshot (iteration {iteration}):
{snapshot}

Return JSON only with this shape:
{{"candidates": [{{"id": "I-001", "title": "short title",
"description": "concrete change",
"evidence": "start with an acceptance/work-item id, or
test:/review:/code:/quality:/failure:, then the observed signal",
"acceptance_criteria": ["observable outcome"],
"expected_files": ["likely/relative/path"],
"focused_commands": ["fast deterministic test command"]}}]}}
Propose at most 5 candidates. Every proposal MUST cite observable evidence
from the delivered product or its quality signals; speculative proposals
without evidence are rejected. Prefer small, evidence-based improvements
over speculative features."""


def _json_object(output: str) -> dict[str, Any]:
    text = output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


class BrainstormStage:
    """DISCOVER: brainstorm improvement candidates from delivered evidence."""

    def __init__(
        self,
        llm,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.track = track

    def run(
        self,
        goal: str,
        acceptance_summary: str,
        iteration: int,
        snapshot,
        tracker=None,
        code_signals: str = "",
        prior_titles: tuple[str, ...] = (),
    ) -> list[ImprovementCandidate]:
        prompt = BRAINSTORM_PROMPT.format(
            goal=goal or "(pure code optimization)",
            acceptance=acceptance_summary or "(none)",
            code_signals=code_signals or "(none)",
            prior="\n".join(f"- {title}" for title in prior_titles) or "(none)",
            iteration=iteration,
            snapshot=snapshot.to_dict() if snapshot is not None else {},
        )
        try:
            output = self.llm.invoke(
                system_prompt=BRAINSTORM_SYSTEM,
                user_prompt=prompt,
                stage_name="harness_brainstorm",
            )
        except Exception:
            if self.track and tracker is not None:
                self.track(tracker, "harness_brainstorm")
            return []
        if self.track and tracker is not None:
            self.track(tracker, "harness_brainstorm")
        data = _json_object(output or "")
        candidates = []
        for raw in data.get("candidates") or []:
            if not isinstance(raw, dict):
                continue
            candidates.append(
                ImprovementCandidate(
                    id=str(raw.get("id") or f"I-{len(candidates) + 1}"),
                    title=str(raw.get("title") or ""),
                    description=str(raw.get("description") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    acceptance_criteria=[
                        str(value) for value in raw.get("acceptance_criteria") or []
                    ],
                    expected_files=[
                        str(value) for value in raw.get("expected_files") or []
                    ],
                    focused_commands=[
                        str(value) for value in raw.get("focused_commands") or []
                    ],
                )
            )
        # Prompt instructions are not a safety boundary. Unsupported ideas do
        # not enter scoring, where a plausible title could otherwise expand
        # the product scope without any observable reason.
        return [
            candidate
            for candidate in candidates
            if candidate.title
            and self._supported_evidence(
                candidate.evidence, acceptance_summary, code_signals
            )
        ]

    @staticmethod
    def _supported_evidence(
        evidence: str, acceptance_summary: str, code_signals: str
    ) -> bool:
        text = str(evidence or "").strip().casefold()
        if not text:
            return False
        references = set()
        for line in f"{acceptance_summary}\n{code_signals}".splitlines():
            match = re.match(r"\s*-\s*([^\s\[]+)", line)
            if match:
                references.add(match.group(1).casefold())
        if any(reference in text for reference in references):
            return True
        return text.startswith(("test:", "review:", "code:", "quality:", "failure:"))


class PrioritizeStage:
    """PRIORITIZE v2: fingerprint dedupe + optional scoring + top-N cap."""

    def __init__(self, scheduler: PlanScheduler | None = None, cap: int = 3):
        self.scheduler = scheduler or PlanScheduler()
        self.cap = cap

    def run(
        self,
        candidates: list[ImprovementCandidate],
        integrated_fingerprints: set[str],
        use_scores: bool = False,
    ) -> tuple[list[ImprovementCandidate], list[ImprovementCandidate]]:
        """Fingerprint dedupe + optional scoring + top-N cap.

        use_scores=False preserves P1 behavior exactly. use_scores=True
        classifies regressions (fingerprint previously integrated), scores
        candidates (None score -> DEFAULT_UNSCORED_SCORE), keeps backlog
        above BACKLOG_THRESHOLD sorted by score desc, parks the candidate
        pool (0.5-0.75) and over-cap backlog, and rejects the rest.
        """
        from onep.harness.scorer import (
            DEFAULT_UNSCORED_SCORE,
            classify,
        )

        backlog: list[ImprovementCandidate] = []
        parked: list[ImprovementCandidate] = []
        seen = set(integrated_fingerprints)
        for candidate in candidates:
            probe = PlanCandidate(
                id=candidate.id,
                title=candidate.title,
                summary=candidate.description,
            )
            candidate.fingerprint = self.scheduler.fingerprint(probe)
            if candidate.fingerprint in integrated_fingerprints:
                candidate.status = "regression" if use_scores else "duplicate"
                parked.append(candidate)
                continue
            if candidate.fingerprint in seen:
                candidate.status = "duplicate"
                parked.append(candidate)
                continue
            seen.add(candidate.fingerprint)
            if not use_scores:
                if len(backlog) < self.cap:
                    candidate.status = "backlog"
                    backlog.append(candidate)
                else:
                    candidate.status = "parked"
                    parked.append(candidate)
                continue
            if candidate.score is None:
                candidate.score = DEFAULT_UNSCORED_SCORE
            candidate.status = classify(candidate.score)
            if candidate.status == "backlog":
                backlog.append(candidate)
            else:
                parked.append(candidate)
        backlog.sort(key=lambda candidate: candidate.score or 0.0, reverse=True)
        overflow = backlog[self.cap :]
        for candidate in overflow:
            candidate.status = "parked"
            parked.append(candidate)
        return backlog[: self.cap], parked
