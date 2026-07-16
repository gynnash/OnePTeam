"""Structured repair feedback and cross-attempt stagnation detection."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


_SUGGESTIONS = {
    "no_changes": "Inspect the target symbol, then make the smallest required edit.",
    "scope_violation": "Revert undeclared files and keep the patch within Plan scope.",
    "test_failed": "Trace the first failing test to the changed code and fix its cause.",
    "review_failed": "Address every blocking review issue without broadening the patch.",
    "developer_stuck": "Change approach: inspect a different source of evidence before editing.",
}


@dataclass(frozen=True)
class RepairBrief:
    failure_type: str
    primary_error: str
    relevant_files: tuple[str, ...]
    diff_sha: str
    previous_actions: tuple[str, ...] = ()
    failing_command: str = ""
    must_preserve: str = (
        "Keep already-correct changes and do not reset or replace the worktree."
    )
    suggested_next_action: str = ""

    @classmethod
    def build(
        cls,
        failure_type: str,
        raw_error: str,
        relevant_files: list[str],
        diff: str,
        previous_actions: list[str] | None = None,
        failing_command: str = "",
    ) -> "RepairBrief":
        return cls(
            failure_type=failure_type,
            primary_error=_primary_error(raw_error),
            relevant_files=tuple(sorted(dict.fromkeys(relevant_files))),
            diff_sha=_sha(diff),
            previous_actions=tuple(previous_actions or ()),
            failing_command=failing_command,
            suggested_next_action=_SUGGESTIONS.get(
                failure_type,
                "Use the gate evidence to make a minimal corrective edit.",
            ),
        )

    @property
    def failure_signature(self) -> str:
        return _sha(json.dumps({
            "failure_type": self.failure_type,
            "primary_error": self.primary_error,
            "failing_command": self.failing_command,
        }, sort_keys=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_type": self.failure_type,
            "primary_error": self.primary_error,
            "relevant_files": list(self.relevant_files),
            "diff_sha": self.diff_sha,
            "previous_actions": list(self.previous_actions),
            "failing_command": self.failing_command,
            "must_preserve": self.must_preserve,
            "suggested_next_action": self.suggested_next_action,
            "failure_signature": self.failure_signature,
        }

    def to_prompt(self) -> str:
        files = ", ".join(self.relevant_files) or "unknown"
        actions = ", ".join(self.previous_actions) or "none recorded"
        command = self.failing_command or "n/a"
        return (
            "Structured repair brief:\n"
            f"- failure_type: {self.failure_type}\n"
            f"- failing_command: {command}\n"
            f"- primary_error: {self.primary_error}\n"
            f"- relevant_files: {files}\n"
            f"- current_diff_sha: {self.diff_sha}\n"
            f"- previous_actions: {actions}\n"
            f"- must_preserve: {self.must_preserve}\n"
            f"- suggested_next_action: {self.suggested_next_action}"
        )


class AttemptStagnationDetector:
    def __init__(self, repeat_limit: int = 3) -> None:
        if repeat_limit < 2:
            raise ValueError("repeat_limit must be at least 2")
        self.repeat_limit = repeat_limit
        self._last_signature = ""
        self._repeats = 0

    def observe(self, brief: RepairBrief) -> bool:
        signature = f"{brief.diff_sha}:{brief.failure_signature}"
        self._repeats = self._repeats + 1 if signature == self._last_signature else 1
        self._last_signature = signature
        return self._repeats >= self.repeat_limit


def previous_tool_actions(events: tuple[dict[str, Any], ...]) -> list[str]:
    actions = []
    for event in events:
        if event.get("type") != "tool_requested":
            continue
        tool = str(event.get("payload", {}).get("tool_name") or "unknown")
        actions.append(tool)
    return actions[-8:]


def _primary_error(raw: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    meaningful = [line for line in lines if line]
    return " | ".join(meaningful[-8:])[:2000] or "No diagnostic output."


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
