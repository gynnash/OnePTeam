"""Structured repair feedback and cross-attempt stagnation detection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Any


_SUGGESTIONS = {
    "no_changes": "Inspect the target symbol, then make the smallest required edit.",
    "scope_violation": "Revert undeclared files and keep the patch within Plan scope.",
    "test_failed": "Trace the first failing test to the changed code and fix its cause.",
    "review_failed": "Address every blocking review issue without broadening the patch.",
    "developer_stuck": "Change approach: inspect a different source of evidence before editing.",
    "implementation_incomplete": (
        "Continue implementing from the current files. Do not run external acceptance "
        "commands until all planned production and pytest files exist."
    ),
}


@dataclass(frozen=True)
class FailureDecision:
    category: str
    retry_lane: str
    retryable: bool
    consume_repair: bool
    diagnostic: str


def classify_exception(error: Exception) -> FailureDecision:
    """Classify orchestration exceptions without treating every error as transport."""
    diagnostic = str(error) or type(error).__name__
    category = classify_failure(diagnostic)
    if category in {"transport_interrupted", "rate_limited", "service_unavailable"}:
        return FailureDecision(category, "transport", True, False, diagnostic)
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return FailureDecision("cancelled", "terminal", False, False, diagnostic)
    return FailureDecision("tool_failed", "tool", False, False, diagnostic)


@dataclass(frozen=True)
class RepairBrief:
    failure_type: str
    failure_category: str
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
        category = classify_failure(raw_error)
        detected_files = extract_relevant_files(raw_error, failing_command)
        combined_files = sorted(
            dict.fromkeys(
                value
                for value in [*relevant_files, *detected_files]
                if not _is_runtime_path(Path(value))
            )
        )
        return cls(
            failure_type=failure_type,
            failure_category=category,
            primary_error=_primary_error(raw_error),
            relevant_files=tuple(combined_files),
            diff_sha=_sha(_semantic_diff(diff)),
            previous_actions=tuple(previous_actions or ()),
            failing_command=failing_command,
            suggested_next_action=_SUGGESTIONS.get(
                category,
                _SUGGESTIONS.get(
                    failure_type,
                    "Use the gate evidence to make a minimal corrective edit.",
                ),
            ),
        )

    @property
    def failure_signature(self) -> str:
        return _sha(
            json.dumps(
                {
                    "failure_type": self.failure_type,
                    "failure_category": self.failure_category,
                    "primary_error": self.primary_error,
                    "failing_command": self.failing_command,
                },
                sort_keys=True,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_type": self.failure_type,
            "failure_category": self.failure_category,
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
            f"- failure_category: {self.failure_category}\n"
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


def has_mutating_action(events: tuple[dict[str, Any], ...]) -> bool:
    """Best-effort check that the current model attempt actually edited files."""
    for event in events:
        if event.get("type") != "tool_requested":
            continue
        payload = event.get("payload", {})
        tool = str(payload.get("tool_name") or "")
        if tool in {"file_write", "edit"}:
            return True
        if tool == "shell":
            command = str((payload.get("tool_args") or {}).get("command") or "")
            if any(
                marker in command
                for marker in (
                    " --fix",
                    "sed -i",
                    " mv ",
                    " cp ",
                    " rm ",
                    "mkdir ",
                    "touch ",
                )
            ):
                return True
    return False


def _primary_error(raw: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    meaningful = [line for line in lines if line]
    pytest_diagnostics = []
    for line in meaningful:
        if (
            line.startswith("FAILED ")
            or line.startswith("ERROR ")
            or line.startswith("E ")
            or "AssertionError" in line
            or re.search(r"(?:test|tests)/[^ ]+\.py:\d+", line)
        ):
            if line not in pytest_diagnostics:
                pytest_diagnostics.append(line)
    if pytest_diagnostics:
        return " | ".join(pytest_diagnostics)[:4000]
    return " | ".join(meaningful[-8:])[:2000] or "No diagnostic output."


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def classify_failure(raw: str) -> str:
    """Classify common deterministic failures before asking another model."""
    lowered = raw.lower()
    rules = (
        (
            "rate_limited",
            ("rate limit", "rate_limit", "ratelimit", "too many requests", "429"),
        ),
        (
            "service_unavailable",
            ("service unavailable", "overloaded", "server error", "503"),
        ),
        (
            "collection_conflict",
            ("import file mismatch", "module/package name collision"),
        ),
        ("no_tests_collected", ("no tests ran", "collected 0 items")),
        (
            "missing_path",
            ("can't open file", "cannot open file", "no such file or directory"),
        ),
        ("fixture_mismatch", ("fixture ", "fixturelookupError".lower())),
        (
            "interface_mismatch",
            (
                "unexpected keyword argument",
                "required positional argument",
                "cannot import name",
                "importerror",
                "modulenotfounderror",
            ),
        ),
        (
            "transport_interrupted",
            (
                "midstreamfallbackerror",
                "apiconnectionerror",
                "incomplete chunked read",
                "peer closed connection",
                "connection reset",
                "connection error",
                "timed out",
                "timeout",
            ),
        ),
        ("assertion_failed", ("assertionerror", "assert ", "indexerror", "keyerror")),
    )
    for category, markers in rules:
        if any(marker in lowered for marker in markers):
            return category
    return "test_failed"


def extract_relevant_files(raw: str, command: str = "") -> list[str]:
    """Extract failing test/source paths so repair prompts point at the cause."""
    values: list[str] = []
    text = f"{raw}\n{command}"
    pattern = re.compile(
        r"(?<![\w.])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_.-]+)?)(?:::\S+)?"
    )
    for match in pattern.finditer(text):
        value = match.group(1).split("::", 1)[0].rstrip(":,)")
        path = Path(value)
        if _is_runtime_path(path) or ".." in path.parts:
            continue
        if value not in values:
            values.append(value)
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = []
    for value in parts:
        value = value.split("::", 1)[0]
        path = Path(value)
        if (
            value.startswith("-")
            or not path.parts
            or _is_runtime_path(path)
            or ".." in path.parts
        ):
            continue
        if ("/" in value or path.suffix) and value not in values:
            values.append(value)
    return values[:20]


def _is_runtime_path(path: Path) -> bool:
    if not path.parts:
        return False
    roots = {
        "tmp",
        "temp",
        ".tmp",
        ".cache",
        "cache",
        "output",
        "outputs",
        "log",
        "logs",
        ".coverage",
        "coverage",
        "htmlcov",
    }
    name = path.name.lower()
    return path.parts[0].lower() in roots or name.endswith(
        (".log", ".db", ".db-wal", ".db-shm", ".db-journal")
    )


def _semantic_diff(diff: str) -> str:
    """Remove generated/runtime-only diff blocks from progress signatures."""
    blocks = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    kept = []
    for block in blocks:
        match = re.match(r"diff --git a/(\S+) b/(\S+)", block)
        if match and all(_is_runtime_path(Path(value)) for value in match.groups()):
            continue
        kept.append(block)
    return "".join(kept)
