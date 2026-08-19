"""Knowledge event models and JSONL persistence for the Knowledge Loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeEventType(str, Enum):
    PROBLEM = "problem"
    DECISION = "decision"
    EXPERIMENT = "experiment"
    FAILURE = "failure"
    DISCOVERY = "discovery"
    INSIGHT = "insight"


@dataclass
class KnowledgeEvent:
    """One distilled, durable engineering knowledge event."""

    type: str
    iteration: int
    problem: str = ""
    options: list[str] = field(default_factory=list)
    selected: str = ""
    reason: str = ""
    evidence: str = ""
    files: list[str] = field(default_factory=list)
    outcome: str = ""
    generalizable: bool = False
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "iteration": self.iteration,
            "problem": self.problem,
            "options": list(self.options),
            "selected": self.selected,
            "reason": self.reason,
            "evidence": self.evidence,
            "files": list(self.files),
            "outcome": self.outcome,
            "generalizable": self.generalizable,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeEvent":
        return cls(
            type=str(data.get("type") or KnowledgeEventType.INSIGHT.value),
            iteration=int(data.get("iteration") or 0),
            problem=str(data.get("problem") or ""),
            options=[str(entry) for entry in data.get("options") or []],
            selected=str(data.get("selected") or ""),
            reason=str(data.get("reason") or ""),
            evidence=str(data.get("evidence") or ""),
            files=[str(entry) for entry in data.get("files") or []],
            outcome=str(data.get("outcome") or ""),
            generalizable=bool(data.get("generalizable", False)),
            created_at=str(data.get("created_at") or _now()),
        )


def load_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, skipping blank and malformed lines."""
    if not Path(path).exists():
        return []
    entries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            entries.append(raw)
    return entries


def load_run_events(run_dir: Path) -> list[dict]:
    """Raw recorder events from <run_dir>/events.jsonl (empty when missing)."""
    return load_jsonl(Path(run_dir) / "events.jsonl")


def distillations_path(run_dir: Path) -> Path:
    return Path(run_dir) / "distillations.jsonl"


def save_distillations(run_dir: Path, events: list[KnowledgeEvent]) -> Path:
    """Append distilled events to <run_dir>/distillations.jsonl."""
    path = distillations_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return path


def load_distillations(run_dir: Path) -> list[KnowledgeEvent]:
    return [
        KnowledgeEvent.from_dict(raw) for raw in load_jsonl(distillations_path(run_dir))
    ]
