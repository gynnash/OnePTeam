"""CrossProjectDistiller: lift generalizable insights into the global vault."""
from __future__ import annotations

import json
from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.vault import VaultWriter

CROSS_SYSTEM = (
    "You are the Cross-Project Distiller for an autonomous development "
    "harness. Distill transferable engineering knowledge. Return JSON only."
)

CROSS_PROMPT = """Lift the generalizable knowledge events below into
cross-project Principles and Patterns.

Project: {project}
Goal: {goal}

Events:
{events}

Return JSON only:
{{"principles": [
  {{"title": "short principle name", "summary": "one-paragraph transferable
  rule", "tags": ["tag"]}}
],
"patterns": [
  {{"title": "short pattern name", "summary": "one-paragraph reusable
  approach", "tags": ["tag"]}}
]}}
A principle is a general engineering rule ("Delay abstraction until the
second consumer"); a pattern is a reusable technique with concrete steps.
Emit at most 3 of each; prefer events with generalizable=true. Either list
may be empty."""


class CrossProjectDistiller:
    """Distills cross-project knowledge into global Principles/Patterns."""

    def __init__(
        self,
        llm,
        writer: VaultWriter,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.writer = writer
        self.track = track

    def run(
        self,
        events: list[dict[str, Any]],
        project: str,
        goal: str,
        tracker=None,
    ) -> list[dict[str, Any]]:
        generalizable = [
            event for event in events if bool(event.get("generalizable"))
        ]
        if not generalizable:
            return []
        try:
            output = self.llm.invoke(
                system_prompt=CROSS_SYSTEM,
                user_prompt=CROSS_PROMPT.format(
                    project=project,
                    goal=goal or "(none)",
                    events=json.dumps(
                        generalizable, ensure_ascii=False, indent=2
                    ),
                ),
                stage_name="harness_cross_distiller",
            )
            if self.track is not None and tracker is not None:
                self.track(tracker, "harness_cross_distiller")
            data = _json_object(output or "")
        except Exception:
            # Distillation is advisory: an LLM failure must never break the
            # completion path or the run that triggered it.
            return []
        written = []
        related = [
            f"[[{VaultWriter.event_note_slug(event)}]]"
            for event in generalizable
        ]
        for section, raw_list in (
            ("Engineering/Principles", data.get("principles") or []),
            ("Engineering/Patterns", data.get("patterns") or []),
        ):
            for raw in raw_list:
                if not isinstance(raw, dict) or not raw.get("title"):
                    continue
                title = str(raw["title"])
                kind = section.split("/")[-1].lower()
                kind = kind[:-1] if kind.endswith("s") else kind
                frontmatter = {
                    "type": kind,
                    "project": project,
                    "iteration": 0,
                    "tags": [str(tag) for tag in raw.get("tags") or []],
                    "created": "",
                    "related": related,
                }
                body = (
                    f"# {title}\n\n"
                    f"## Summary\n\n{raw.get('summary', '')}\n\n"
                    f"## Source\n\n"
                    f"Lifted from `{project}` (goal: {goal or '(none)'}).\n\n"
                    + "\n".join(f"- {link}" for link in related)
                )
                path = self.writer.write_note(
                    section, title, frontmatter, body
                )
                written.append({
                    "section": section,
                    "title": title,
                    "path": str(path),
                })
        return written
