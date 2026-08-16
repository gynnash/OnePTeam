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

Quality snapshot (iteration {iteration}):
{snapshot}

Return JSON only with this shape:
{{"candidates": [{{"id": "I-001", "title": "short title",
"description": "concrete change"}}]}}
Propose at most 5 candidates. Prefer small, evidence-based improvements
over speculative features."""


def _json_object(output: str) -> dict[str, Any]:
    text = output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
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
    ) -> list[ImprovementCandidate]:
        prompt = BRAINSTORM_PROMPT.format(
            goal=goal,
            acceptance=acceptance_summary or "(none)",
            iteration=iteration,
            snapshot=snapshot.to_dict() if snapshot is not None else {},
        )
        output = self.llm.invoke(
            system_prompt=BRAINSTORM_SYSTEM,
            user_prompt=prompt,
            stage_name="harness_brainstorm",
        )
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
                )
            )
        return [c for c in candidates if c.title]


class PrioritizeStage:
    """PRIORITIZE v1: fingerprint dedupe + top-N cap. Scorer arrives in P2."""

    def __init__(self, scheduler: PlanScheduler | None = None, cap: int = 3):
        self.scheduler = scheduler or PlanScheduler()
        self.cap = cap

    def run(
        self,
        candidates: list[ImprovementCandidate],
        integrated_fingerprints: set[str],
    ) -> tuple[list[ImprovementCandidate], list[ImprovementCandidate]]:
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
            if candidate.fingerprint in seen:
                candidate.status = "duplicate"
                parked.append(candidate)
                continue
            seen.add(candidate.fingerprint)
            if len(backlog) < self.cap:
                candidate.status = "backlog"
                backlog.append(candidate)
            else:
                candidate.status = "parked"
                parked.append(candidate)
        return backlog, parked
