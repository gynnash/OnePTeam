"""Opportunity Scorer: deterministic weighted formula + LLM dimensions.

Spec §5.2: Score = 0.30V + 0.20Q + 0.15R + 0.15E - 0.10C - 0.10Risk,
normalized by the positive weight sum (0.80) so Score in [-0.25, 1.0].
Score > 0.75 -> backlog; 0.5-0.75 -> candidate pool; < 0.5 -> reject.
"""
from __future__ import annotations

from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.models import ImprovementCandidate

SCORE_WEIGHTS = {
    "V": 0.30,     # user value
    "Q": 0.20,     # quality gain
    "R": 0.15,     # relevance to original goal
    "E": 0.15,     # learning value
    "C": 0.10,     # cost
    "Risk": 0.10,  # complexity risk
}
POSITIVE_WEIGHT_SUM = 0.80
BACKLOG_THRESHOLD = 0.75
CANDIDATE_POOL_THRESHOLD = 0.50
DEFAULT_UNSCORED_SCORE = 0.80

COST_DIMENSIONS = {"C", "Risk"}

SCORER_SYSTEM = (
    "You are the opportunity scorer for an autonomous development harness. "
    "Score every candidate dimension 0-1 with a rationale. Return JSON only."
)

SCORER_PROMPT = """Score each improvement candidate on six dimensions, each 0-1:
V = user value, Q = quality gain, R = relevance to the original goal,
E = learning value, C = cost (higher = more expensive),
Risk = complexity risk (higher = riskier).

Original goal: {goal}

Acceptance summary:
{acceptance}

Candidates (iteration {iteration}):
{candidates}

Return JSON only:
{{"scores": [{{"id": "<candidate id>", "V": 0.0, "Q": 0.0, "R": 0.0,
"E": 0.0, "C": 0.0, "Risk": 0.0, "rationale": "one sentence"}}]}}"""


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def compute_score(dimensions: dict[str, float]) -> float:
    weighted = 0.0
    for dimension, weight in SCORE_WEIGHTS.items():
        value = clamp01(dimensions.get(dimension))
        sign = -1.0 if dimension in COST_DIMENSIONS else 1.0
        weighted += sign * weight * value
    return round(weighted / POSITIVE_WEIGHT_SUM, 4)


def classify(score: float) -> str:
    if score > BACKLOG_THRESHOLD:
        return "backlog"
    if score >= CANDIDATE_POOL_THRESHOLD:
        return "parked"
    return "rejected"


class OpportunityScorer:
    """LLM scores dimensions; the harness computes the weighted total."""

    def __init__(
        self,
        llm,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.track = track

    def score_candidates(
        self,
        candidates: list[ImprovementCandidate],
        goal: str,
        acceptance_summary: str,
        iteration: int,
        tracker=None,
    ) -> list[ImprovementCandidate]:
        if not candidates:
            return []
        import json
        try:
            output = self.llm.invoke(
                system_prompt=SCORER_SYSTEM,
                user_prompt=SCORER_PROMPT.format(
                    goal=goal or "(pure code optimization)",
                    acceptance=acceptance_summary or "(none)",
                    iteration=iteration,
                    candidates=json.dumps(
                        [
                            {"id": candidate.id, "title": candidate.title,
                             "description": candidate.description,
                             "evidence": candidate.evidence}
                            for candidate in candidates
                        ],
                        ensure_ascii=False, indent=2,
                    ),
                ),
                stage_name="harness_scorer",
            )
        except Exception:
            # Transient LLM failure must not fail the run: score every
            # candidate with the default (nothing usable -> 0.80).
            if self.track is not None and tracker is not None:
                self.track(tracker, "harness_scorer")
            for candidate in candidates:
                candidate.score = DEFAULT_UNSCORED_SCORE
                candidate.dimensions = {"rationale": "scorer unavailable"}
            return candidates
        if self.track is not None and tracker is not None:
            self.track(tracker, "harness_scorer")
        data = _json_object(output or "")
        by_id: dict[str, dict[str, Any]] = {}
        for entry in data.get("scores") or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            dims = {key: entry[key] for key in SCORE_WEIGHTS
                    if key in entry}
            if "rationale" in entry:
                dims["rationale"] = entry["rationale"]
            by_id[str(entry["id"])] = dims
        for candidate in candidates:
            dims = by_id.get(candidate.id)
            if dims is None:
                candidate.score = DEFAULT_UNSCORED_SCORE
                candidate.dimensions = {"rationale": "scorer unavailable"}
                continue
            if not any(key in SCORE_WEIGHTS for key in dims):
                # Matched id but no usable dimension scores (only id and/or
                # rationale): keep the "nothing usable -> 0.80" promise
                # instead of computing 0.0 and rejecting the candidate.
                candidate.score = DEFAULT_UNSCORED_SCORE
                candidate.dimensions = {
                    "rationale": "scorer returned no dimensions",
                }
                continue
            candidate.dimensions = dims
            candidate.score = compute_score(dims)
        return candidates
