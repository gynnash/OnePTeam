"""KnowledgeDistiller: LLM filtering/structuring of raw harness events."""

from __future__ import annotations

import json
from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.knowledge_models import (
    KnowledgeEvent,
    KnowledgeEventType,
)

DISTILLER_SYSTEM = (
    "You are the Knowledge Distiller for an autonomous development harness. "
    "You filter noisy raw operation logs into durable engineering knowledge. "
    "Return JSON only."
)

DISTILLER_PROMPT = """Distill the raw development events below into durable
knowledge events.

Checkpoint: {checkpoint}
Iteration: {iteration}
Context:
{context}

Raw events (JSON):
{events}

Return JSON only with this shape:
{{"events": [
  {{"type": "problem|decision|experiment|failure|discovery|insight",
    "problem": "what was being solved",
    "options": ["option a", "option b"],
    "selected": "what was chosen (decisions only)",
    "reason": "why (decisions/failures)",
    "evidence": "what was observed",
    "files": ["relative/path"],
    "outcome": "what happened after",
    "generalizable": true/false}}
]}}

Rules:
1. Discard operational noise: traces, token counts, tool calls, logs.
2. A failed-repair loop (one retry_count entry with attempts) becomes ONE
   failure event, plus at most one insight event about the root cause.
   Never emit one event per retry.
3. Weight these high-value signals highest when deciding what to keep:
   - debugging difficulty (long, obscure failures)
   - failed hypotheses (explicit beliefs that were disproven)
   - unexpected discoveries (results that contradicted expectations)
   - reusable knowledge (techniques that apply to other projects)
   - decision irreversibility (hard-to-undo choices deserve a note)
4. Set generalizable=true only when the learning transfers beyond this
   project. Emit at most 6 events per checkpoint; prefer quality over
   quantity. An empty list is a valid answer."""


class KnowledgeDistiller:
    """Structures raw harness events into KnowledgeEvents at checkpoints."""

    def __init__(
        self,
        llm,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.track = track

    def distill(
        self,
        raw_events: list[dict[str, Any]],
        checkpoint: str,
        iteration: int,
        context: str = "",
        tracker=None,
        collapse: bool = True,
    ) -> list[KnowledgeEvent]:
        if not raw_events:
            return []
        rendered = self.collapse_repair_loops(raw_events) if collapse else raw_events
        output = self.llm.invoke(
            system_prompt=DISTILLER_SYSTEM,
            user_prompt=DISTILLER_PROMPT.format(
                checkpoint=checkpoint,
                iteration=iteration,
                context=context or "(none)",
                events=json.dumps(
                    rendered,
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
            stage_name="harness_distiller",
        )
        if self.track is not None and tracker is not None:
            self.track(tracker, "harness_distiller")
        data = _json_object(output or "")
        events = []
        valid_types = {event_type.value for event_type in KnowledgeEventType}
        for raw in data.get("events") or []:
            if len(events) >= 6:
                break
            if not isinstance(raw, dict):
                continue
            event_type = str(raw.get("type") or "").lower()
            if event_type not in valid_types:
                continue
            events.append(
                KnowledgeEvent(
                    type=event_type,
                    iteration=int(raw.get("iteration") or iteration),
                    problem=str(raw.get("problem") or ""),
                    options=[str(entry) for entry in raw.get("options") or []],
                    selected=str(raw.get("selected") or ""),
                    reason=str(raw.get("reason") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    files=[str(entry) for entry in raw.get("files") or []],
                    outcome=str(raw.get("outcome") or ""),
                    generalizable=bool(raw.get("generalizable", False)),
                )
            )
        return events

    @staticmethod
    def collapse_repair_loops(
        raw_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Collapse each slice's failed-repair loop into one entry.

        The greenfield kernel records one "repair_brief" event per failed
        repair attempt and starts every slice attempt with a "SLICE i/n"
        trace (greenfield/engine.py:276). Every successful slice ends with
        a trace whose label is exactly "SLICE" (line 438). Entries are
        grouped per slice using these completion traces as separators; other
        noise (traces, engineer_trajectory) is dropped, and the repair_brief
        entries between two completion traces merge into a single entry
        carrying retry_count and the full attempt trail. Do NOT broaden the
        separator predicate to startswith("SLICE"): attempt-start traces
        would then split every retry into its own group, violating spec
        §6.1 (one Failure per loop).
        """
        merged: list[dict[str, Any]] = []
        repair_group: dict[str, Any] | None = None
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            etype = str(event.get("type") or "")
            payload = event.get("payload")
            is_slice_trace = (
                etype == "trace"
                and isinstance(payload, dict)
                and str(payload.get("label") or "") == "SLICE"
            )
            if is_slice_trace:
                if repair_group is not None:
                    merged.append(repair_group)
                    repair_group = None
                continue
            if etype == "repair_brief":
                if repair_group is None:
                    repair_group = {
                        "type": "repair_brief",
                        "payload": {"retry_count": 0, "attempts": []},
                    }
                repair_group["payload"]["retry_count"] += 1
                repair_group["payload"]["attempts"].append(payload or {})
                continue
            if etype in {"trace", "engineer_trajectory"}:
                continue
            if repair_group is not None:
                merged.append(repair_group)
                repair_group = None
            merged.append(event)
        if repair_group is not None:
            merged.append(repair_group)
        return merged
