"""Analyzer utilities: response parsing."""
from __future__ import annotations

import json

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
