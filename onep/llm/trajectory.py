"""Structured trajectory events and deterministic loop-stall detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable


TrajectorySink = Callable[[dict[str, Any]], None]


@dataclass
class TrajectoryRecorder:
    sink: TrajectorySink | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "sequence": len(self.events) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": payload,
        }
        self.events.append(event)
        if self.sink:
            self.sink(event)
        return event


class StuckDetector:
    """Detect repeated actions/results that produce no new observations."""

    def __init__(self, repeat_limit: int = 3) -> None:
        if repeat_limit < 2:
            raise ValueError("repeat_limit must be at least 2")
        self.repeat_limit = repeat_limit
        self._last_call = ""
        self._call_repeats = 0
        self._last_result = ""
        self._result_repeats = 0

    def observe_call(self, tool_name: str, args: dict[str, Any]) -> str | None:
        signature = _signature({"tool": tool_name, "args": args})
        self._call_repeats = (
            self._call_repeats + 1 if signature == self._last_call else 1
        )
        self._last_call = signature
        if self._call_repeats >= self.repeat_limit:
            return f"repeated_tool_call:{tool_name}"
        return None

    def observe_result(self, tool_name: str, result: str) -> str | None:
        signature = _signature({
            "call": self._last_call,
            "tool": tool_name,
            "result": result,
        })
        self._result_repeats = (
            self._result_repeats + 1 if signature == self._last_result else 1
        )
        self._last_result = signature
        if self._result_repeats >= self.repeat_limit:
            return f"repeated_tool_result:{tool_name}"
        return None


def _signature(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
