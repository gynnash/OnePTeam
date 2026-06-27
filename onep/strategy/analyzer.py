"""Analyzer utilities: response parsing."""
from __future__ import annotations

import json
from pathlib import Path

from onep.strategy.models import StrategyItem


def parse_analysis_response(response: str) -> list[StrategyItem]:
    """Parse LLM JSONL response into StrategyItem objects.

    Skips invalid lines gracefully instead of crashing.
    """
    items = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            items.append(StrategyItem(
                title=obj["title"],
                file_location=obj["file_location"],
                tags=obj.get("tags", []),
                impact=obj.get("impact", "medium"),
                summary=obj.get("summary", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            continue

    impact_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: impact_order.get(x.impact, 2))
    return items


def parse_streaming_items(accumulator: str) -> tuple[list[dict], str]:
    """Parse complete JSON lines from accumulated text.
    Returns (parsed_items, remaining_text)."""
    lines = accumulator.split("\n")
    items = []
    for line in lines[:-1]:
        line = line.strip()
        if line:
            item = _try_parse_item(line)
            if item:
                items.append(item)
    return items, lines[-1]


def _try_parse_item(line: str) -> dict | None:
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


def save_analysis_items(workspace: Path, items: list[dict]) -> None:
    """Append analysis items to JSONL file."""
    path = workspace / "analysis_items.jsonl"
    with open(path, "a") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()


def load_analysis_items(workspace: Path) -> list[dict]:
    """Load all previously saved analysis items."""
    path = workspace / "analysis_items.jsonl"
    if not path.exists():
        return []
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items
