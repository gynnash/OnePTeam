"""Durable, concurrent-safe recording for optimize runs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Iterator

import yaml

from onep.strategy.optimize_models import (
    AttemptRecord,
    PlanRecord,
    PlanStatus,
    ReviewResult,
    RunRecord,
    RunStatus,
)


_SAFE_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_RUN_TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.PARTIAL,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}
_RUN_STATUS_PRIORITY = {
    RunStatus.PENDING: 0,
    RunStatus.RUNNING: 1,
    **{status: 2 for status in _RUN_TERMINAL_STATUSES},
}
_PLAN_TERMINAL_STATUSES = {
    PlanStatus.INTEGRATED,
    PlanStatus.ROLLED_BACK,
    PlanStatus.SKIPPED,
}
_PLAN_STATUS_PRIORITY = {
    PlanStatus.PENDING: 0,
    PlanStatus.PLANNED: 1,
    PlanStatus.PLAN_READY: 2,
    PlanStatus.BRANCH_CREATED: 3,
    PlanStatus.DEVELOPING: 4,
    PlanStatus.TESTING: 5,
    PlanStatus.REVIEWING: 6,
    PlanStatus.REPAIRING: 7,
    PlanStatus.FIXING: 7,
    PlanStatus.PASSED: 8,
    PlanStatus.COMMITTED: 9,
    PlanStatus.INTEGRATING: 10,
    PlanStatus.FAILED: 11,
    PlanStatus.INTEGRATED: 12,
    PlanStatus.ROLLED_BACK: 12,
    PlanStatus.SKIPPED: 12,
}
_PLAN_ALLOWED_TRANSITIONS = {
    PlanStatus.PENDING: {
        PlanStatus.PLANNED,
        PlanStatus.PLAN_READY,
        PlanStatus.FAILED,
        PlanStatus.SKIPPED,
    },
    PlanStatus.PLANNED: {
        PlanStatus.PLAN_READY,
        PlanStatus.BRANCH_CREATED,
        PlanStatus.DEVELOPING,
        PlanStatus.FAILED,
        PlanStatus.SKIPPED,
    },
    PlanStatus.PLAN_READY: {
        PlanStatus.BRANCH_CREATED, PlanStatus.FAILED, PlanStatus.SKIPPED,
    },
    PlanStatus.BRANCH_CREATED: {
        PlanStatus.DEVELOPING, PlanStatus.FAILED,
    },
    PlanStatus.DEVELOPING: {PlanStatus.TESTING, PlanStatus.FAILED},
    PlanStatus.TESTING: {
        PlanStatus.REVIEWING,
        PlanStatus.REPAIRING,
        PlanStatus.FIXING,
        PlanStatus.FAILED,
    },
    PlanStatus.REVIEWING: {
        PlanStatus.REPAIRING,
        PlanStatus.FIXING,
        PlanStatus.PASSED,
        PlanStatus.COMMITTED,
        PlanStatus.FAILED,
    },
    PlanStatus.REPAIRING: {
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.FAILED,
    },
    PlanStatus.FIXING: {
        PlanStatus.DEVELOPING, PlanStatus.TESTING, PlanStatus.FAILED,
    },
    PlanStatus.PASSED: {PlanStatus.COMMITTED, PlanStatus.FAILED},
    PlanStatus.COMMITTED: {
        PlanStatus.INTEGRATING,
        PlanStatus.INTEGRATED,
        PlanStatus.FAILED,
    },
    PlanStatus.INTEGRATING: {
        PlanStatus.INTEGRATED, PlanStatus.FAILED,
    },
    PlanStatus.FAILED: {PlanStatus.ROLLED_BACK},
    PlanStatus.INTEGRATED: set(),
    PlanStatus.ROLLED_BACK: set(),
    PlanStatus.SKIPPED: set(),
}


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, (str, int, float, bool, Path, Enum)):
                raise TypeError(
                    f"Unsupported mapping key type: {type(key).__name__}"
                )
            result[str(_safe_value(key))] = _safe_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_safe_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:
    safe_data = _safe_value(data)
    content = yaml.safe_dump(safe_data, allow_unicode=True, sort_keys=False)
    _atomic_text_write(path, content)


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    content = json.dumps(_safe_value(data), ensure_ascii=False, indent=2) + "\n"
    _atomic_text_write(path, content)


def _merge_attempts(
    old: list[AttemptRecord],
    new: list[AttemptRecord],
) -> list[AttemptRecord]:
    if not new:
        return list(old)
    merged = {attempt.number: attempt for attempt in old}
    for attempt in new:
        existing = merged.get(attempt.number)
        if existing is None:
            merged[attempt.number] = attempt
            continue
        data = existing.to_dict()
        incoming = attempt.to_dict()
        for field_name in ("branch", "base_commit"):
            if incoming[field_name]:
                data[field_name] = incoming[field_name]
        for field_name in (
            "changed_files",
            "test_results",
            "feedback",
        ):
            if incoming[field_name]:
                data[field_name] = incoming[field_name]
        if attempt.review is not None:
            data["review"] = incoming["review"]
        if attempt.cost:
            data["cost"] = attempt.cost
        data["artifacts"] = {
            **existing.artifacts,
            **attempt.artifacts,
        }
        merged[attempt.number] = AttemptRecord.from_dict(_safe_value(data))
    return [merged[number] for number in sorted(merged)]


def _merge_plan(old: PlanRecord, new: PlanRecord) -> PlanRecord:
    old_data = old.to_dict()
    new_data = new.to_dict()
    old_data["candidate"] = new_data["candidate"]
    if _status_can_advance(
        old.status,
        new.status,
        _PLAN_STATUS_PRIORITY,
        _PLAN_TERMINAL_STATUSES,
        _PLAN_ALLOWED_TRANSITIONS,
    ):
        old_data["status"] = new.status.value
    for field_name in ("branch", "base_commit", "commit_sha"):
        if new_data[field_name]:
            old_data[field_name] = new_data[field_name]
    old_data["attempts"] = [
        attempt.to_dict()
        for attempt in _merge_attempts(old.attempts, new.attempts)
    ]
    if new.failure_reason is not None:
        old_data["failure_reason"] = new.failure_reason.value
    if new.failure_detail:
        old_data["failure_detail"] = new.failure_detail
    old_data["artifacts"] = {
        **old.artifacts,
        **new.artifacts,
    }
    return PlanRecord.from_dict(_safe_value(old_data))


def _merge_run(old: RunRecord, new: RunRecord) -> RunRecord:
    data = old.to_dict()
    if _status_can_advance(
        old.status,
        new.status,
        _RUN_STATUS_PRIORITY,
        _RUN_TERMINAL_STATUSES,
    ):
        data["status"] = new.status.value
    if new.total_cost:
        data["total_cost"] = new.total_cost
    for field_name in ("base_commit", "integration_branch"):
        value = getattr(new, field_name)
        if value:
            data[field_name] = value
    if new.failure_reason is not None:
        data["failure_reason"] = new.failure_reason.value
    if new.failure_detail:
        data["failure_detail"] = new.failure_detail
    data["artifacts"] = {**old.artifacts, **new.artifacts}

    plans = {plan.candidate.id: plan for plan in old.plans}
    for plan in new.plans:
        existing = plans.get(plan.candidate.id)
        plans[plan.candidate.id] = (
            _merge_plan(existing, plan) if existing else plan
        )
    data["plans"] = [plan.to_dict() for plan in plans.values()]
    return RunRecord.from_dict(_safe_value(data))


def _merge_plan_optimistic(
    persisted: PlanRecord,
    incoming: PlanRecord,
    baseline: PlanRecord | None,
) -> PlanRecord:
    if baseline is None:
        return _merge_plan(persisted, incoming)
    if incoming.to_dict() == baseline.to_dict():
        return persisted

    data = persisted.to_dict()
    incoming_data = incoming.to_dict()
    baseline_data = baseline.to_dict()
    persisted_changed = (
        _fingerprint(persisted.to_dict())
        != _fingerprint(baseline.to_dict())
    )
    if (
        incoming_data["candidate"] != baseline_data["candidate"]
        and not persisted_changed
    ):
        data["candidate"] = incoming_data["candidate"]
    if incoming.status != baseline.status:
        if not persisted_changed:
            accept_status = _status_can_advance(
                baseline.status,
                incoming.status,
                _PLAN_STATUS_PRIORITY,
                _PLAN_TERMINAL_STATUSES,
                _PLAN_ALLOWED_TRANSITIONS,
            )
        elif persisted.status in _PLAN_TERMINAL_STATUSES:
            accept_status = False
        else:
            accept_status = (
                incoming.status
                in _PLAN_ALLOWED_TRANSITIONS[persisted.status]
            )
        if accept_status:
            data["status"] = incoming.status.value
    for field_name in ("branch", "base_commit", "commit_sha"):
        if (
            incoming_data[field_name] != baseline_data[field_name]
            and incoming_data[field_name]
            and (
                not persisted_changed
                or not data[field_name]
            )
        ):
            data[field_name] = incoming_data[field_name]
    if incoming_data["attempts"] != baseline_data["attempts"]:
        merged_attempts = (
            _merge_attempts(incoming.attempts, persisted.attempts)
            if persisted_changed
            else _merge_attempts(persisted.attempts, incoming.attempts)
        )
        data["attempts"] = [
            attempt.to_dict()
            for attempt in merged_attempts
        ]
    if (
        incoming.failure_reason != baseline.failure_reason
        and incoming.failure_reason is not None
        and (
            not persisted_changed
            or persisted.failure_reason is None
        )
    ):
        data["failure_reason"] = incoming.failure_reason.value
    if (
        incoming.failure_detail != baseline.failure_detail
        and incoming.failure_detail
        and (
            not persisted_changed
            or not persisted.failure_detail
        )
    ):
        data["failure_detail"] = incoming.failure_detail
    if incoming.artifacts != baseline.artifacts:
        data["artifacts"] = (
            {
                **incoming.artifacts,
                **persisted.artifacts,
            }
            if persisted_changed
            else {
                **persisted.artifacts,
                **incoming.artifacts,
            }
        )
    return PlanRecord.from_dict(_safe_value(data))


def _merge_run_optimistic(
    persisted: RunRecord,
    incoming: RunRecord,
    baseline: RunRecord,
) -> RunRecord:
    data = persisted.to_dict()
    persisted_changed = (
        _fingerprint(persisted.to_dict())
        != _fingerprint(baseline.to_dict())
    )
    status_is_active_update = (
        incoming.status != baseline.status
        and _status_can_advance(
            baseline.status,
            incoming.status,
            _RUN_STATUS_PRIORITY,
            _RUN_TERMINAL_STATUSES,
        )
    )
    if status_is_active_update and not (
        persisted_changed
        and persisted.status in _RUN_TERMINAL_STATUSES
    ):
        data["status"] = incoming.status.value
    for field_name in (
        "total_cost",
        "base_commit",
        "integration_branch",
    ):
        incoming_value = getattr(incoming, field_name)
        if incoming_value != getattr(baseline, field_name):
            data[field_name] = incoming_value
    if (
        incoming.failure_reason != baseline.failure_reason
        and incoming.failure_reason is not None
    ):
        data["failure_reason"] = incoming.failure_reason.value
    if (
        incoming.failure_detail != baseline.failure_detail
        and incoming.failure_detail
    ):
        data["failure_detail"] = incoming.failure_detail
    if incoming.artifacts != baseline.artifacts:
        data["artifacts"] = {
            **persisted.artifacts,
            **incoming.artifacts,
        }

    persisted_plans = {
        plan.candidate.id: plan for plan in persisted.plans
    }
    baseline_plans = {
        plan.candidate.id: plan for plan in baseline.plans
    }
    for plan in incoming.plans:
        existing = persisted_plans.get(plan.candidate.id)
        if existing is None:
            persisted_plans[plan.candidate.id] = plan
            continue
        persisted_plans[plan.candidate.id] = _merge_plan_optimistic(
            existing,
            plan,
            baseline_plans.get(plan.candidate.id),
        )
    data["plans"] = [plan.to_dict() for plan in persisted_plans.values()]
    return RunRecord.from_dict(_safe_value(data))


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        _safe_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _status_can_advance(
    old: Any,
    new: Any,
    priorities: dict[Any, int],
    terminal_statuses: set[Any],
    allowed_transitions: dict[Any, set[Any]] | None = None,
) -> bool:
    if old == new:
        return True
    if (
        allowed_transitions is not None
        and new in allowed_transitions[old]
    ):
        return True
    if old in terminal_statuses:
        return False
    if priorities[new] <= priorities[old]:
        return False
    if allowed_transitions is None:
        return True
    pending = list(allowed_transitions[old])
    visited = {old}
    while pending:
        status = pending.pop()
        if status == new:
            return True
        if status in visited:
            continue
        visited.add(status)
        pending.extend(allowed_transitions[status])
    return False


class OptimizeRunRecorder:
    """Persist run state and evidence independently from Git worktrees."""

    def __init__(self, run_dir: Path, run: RunRecord) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._root = self.run_dir.resolve()
        self._safe_target("plans").mkdir(parents=True, exist_ok=True)
        self._thread_lock = self._lock_for_root()
        normalized = RunRecord.from_dict(_safe_value(run.to_dict()))

        with self._locked():
            state_path = self._safe_target("run.yaml")
            if state_path.exists():
                self._accept_run(self._load_state_locked())
            else:
                self._save_state_locked(normalized)
                self._accept_run(normalized)

    @classmethod
    def load(cls, run_dir: Path) -> OptimizeRunRecorder:
        recorder = cls.__new__(cls)
        recorder.run_dir = Path(run_dir)
        recorder._root = recorder.run_dir.resolve()
        recorder._thread_lock = recorder._lock_for_root()
        with recorder._locked():
            run = recorder._load_state_locked()
            recovered = recorder._recover_child_plans_locked(run)
            if recovered:
                recorder._save_state_locked(run)
            recorder._accept_run(run)
        return recorder

    def save_state(self) -> None:
        snapshot = self.run
        normalized = RunRecord.from_dict(_safe_value(snapshot.to_dict()))
        try:
            with self._locked():
                latest = self._load_state_locked()
                working = _merge_run_optimistic(
                    latest,
                    normalized,
                    self._baseline_run,
                )
                self._save_state_locked(working)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        safe_event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": _safe_value(event_type),
            "payload": _safe_value(payload),
        }
        encoded = (
            json.dumps(safe_event, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        snapshot = self.run
        try:
            with self._locked():
                working = self._load_state_locked()
                self._append_event_locked(encoded)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_plan(self, plan: PlanRecord, plan_markdown: str) -> None:
        normalized = PlanRecord.from_dict(_safe_value(plan.to_dict()))
        if not isinstance(plan_markdown, str):
            raise TypeError("plan_markdown must be a string")
        item_id = normalized.candidate.id
        self._plan_dir(item_id)
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                existing = self._find_plan_in(working, item_id, required=False)
                baseline = self._find_plan_in(
                    self._baseline_run,
                    item_id,
                    required=False,
                )
                merged = (
                    _merge_plan_optimistic(
                        existing,
                        normalized,
                        baseline,
                    )
                    if existing is not None
                    else normalized
                )
                self._replace_plan(working, merged)
                plan_dir = self._plan_dir(item_id)
                plan_dir.mkdir(parents=True, exist_ok=True)
                self._atomic_yaml_locked(
                    plan_dir / "plan.yaml",
                    merged.to_dict(),
                )
                self._write_plan_indexes_locked(merged)
                self._atomic_text_locked(
                    plan_dir / "plan.md",
                    plan_markdown,
                )
                self._save_state_locked(working)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_attempt(self, item_id: str, attempt: AttemptRecord) -> None:
        normalized = AttemptRecord.from_dict(_safe_value(attempt.to_dict()))
        self._attempt_dir(item_id, normalized.number)
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                plan = self._find_plan_in(working, item_id)
                plan.attempts = _merge_attempts(
                    plan.attempts,
                    [normalized],
                )
                merged_attempt = self._find_attempt(
                    plan,
                    normalized.number,
                )
                attempt_dir = self._attempt_dir(item_id, normalized.number)
                attempt_dir.mkdir(parents=True, exist_ok=True)
                self._atomic_yaml_locked(
                    attempt_dir / "attempt.yaml",
                    merged_attempt.to_dict(),
                )
                self._sync_plan_locked(working, plan)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_review(
        self,
        item_id: str,
        attempt_no: int,
        review: ReviewResult,
    ) -> None:
        normalized = ReviewResult.from_dict(_safe_value(review.to_dict()))
        self._attempt_dir(item_id, attempt_no)
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                plan = self._find_plan_in(working, item_id)
                attempt = self._find_attempt(plan, attempt_no)
                attempt.review = normalized
                attempt_dir = self._attempt_dir(item_id, attempt_no)
                self._atomic_json_locked(
                    attempt_dir / "review.json",
                    normalized.to_dict(),
                )
                self._sync_attempt_locked(working, plan, attempt)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_test_output(
        self,
        item_id: str,
        attempt_no: int,
        output: str,
    ) -> None:
        if not isinstance(output, str):
            raise TypeError("output must be a string")
        self._attempt_dir(item_id, attempt_no)
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                plan = self._find_plan_in(working, item_id)
                attempt = self._find_attempt(plan, attempt_no)
                self._atomic_text_locked(
                    self._attempt_dir(item_id, attempt_no)
                    / "test-output.txt",
                    output,
                )
                self._sync_attempt_locked(working, plan, attempt)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_diff(self, item_id: str, diff: str) -> None:
        if not isinstance(diff, str):
            raise TypeError("diff must be a string")
        self._plan_dir(item_id)
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                plan = self._find_plan_in(working, item_id)
                self._atomic_text_locked(
                    self._plan_dir(item_id) / "final.diff",
                    diff,
                )
                self._sync_plan_locked(working, plan)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def save_report(self, markdown: str) -> None:
        if not isinstance(markdown, str):
            raise TypeError("markdown must be a string")
        self._safe_target("report.md")
        snapshot = self.run
        try:
            with self._locked():
                working = self._working_from_disk_locked()
                self._atomic_text_locked(
                    self._safe_target("report.md"),
                    markdown,
                )
                self._save_state_locked(working)
                self._accept_run(working)
        except Exception:
            self.run = snapshot
            raise

    def _lock_for_root(self) -> threading.RLock:
        key = str(self._root)
        with _THREAD_LOCKS_GUARD:
            return _THREAD_LOCKS.setdefault(key, threading.RLock())

    def _accept_run(self, run: RunRecord) -> None:
        normalized = RunRecord.from_dict(_safe_value(run.to_dict()))
        self.run = normalized
        self._baseline_run = RunRecord.from_dict(normalized.to_dict())
        self._last_seen_run_fingerprint = _fingerprint(
            normalized.to_dict()
        )
        self._last_seen_plan_fingerprints = {
            plan.candidate.id: _fingerprint(plan.to_dict())
            for plan in normalized.plans
        }

    def _working_from_disk_locked(self) -> RunRecord:
        persisted = self._load_state_locked()
        return _merge_run_optimistic(
            persisted,
            self.run,
            self._baseline_run,
        )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self._safe_target(".recorder.lock")
        with self._thread_lock:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _safe_target(self, *parts: str) -> Path:
        candidate = self.run_dir.joinpath(*parts)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(
                f"Target resolves outside run_dir: {candidate}"
            ) from exc
        return candidate

    def _plan_dir(self, item_id: str) -> Path:
        if not isinstance(item_id, str) or not _SAFE_ITEM_ID.fullmatch(item_id):
            raise ValueError(f"Unsafe item_id: {item_id!r}")
        return self._safe_target("plans", item_id)

    def _attempt_dir(self, item_id: str, attempt_no: int) -> Path:
        if not isinstance(attempt_no, int) or attempt_no < 1:
            raise ValueError("attempt_no must be a positive integer")
        return self._safe_target(
            "plans",
            item_id,
            "attempts",
            str(attempt_no),
        )

    def _atomic_text_locked(self, path: Path, content: str) -> None:
        self._ensure_safe_path(path)
        _atomic_text_write(path, content)

    def _atomic_yaml_locked(
        self,
        path: Path,
        data: dict[str, Any],
    ) -> None:
        self._ensure_safe_path(path)
        _atomic_yaml_write(path, data)

    def _atomic_json_locked(
        self,
        path: Path,
        data: dict[str, Any],
    ) -> None:
        self._ensure_safe_path(path)
        _atomic_json_write(path, data)

    def _ensure_safe_path(self, path: Path) -> None:
        relative = path.relative_to(self.run_dir)
        self._safe_target(*relative.parts)

    def _save_state_locked(self, run: RunRecord) -> None:
        self._atomic_yaml_locked(
            self._safe_target("run.yaml"),
            run.to_dict(),
        )

    def _load_state_locked(self) -> RunRecord:
        state_path = self._safe_target("run.yaml")
        try:
            raw = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("run.yaml must contain a mapping")
            return RunRecord.from_dict(_safe_value(raw))
        except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Unable to load optimize run from {state_path}: {exc}"
            ) from exc

    def _recover_child_plans_locked(self, run: RunRecord) -> bool:
        plans_dir = self._safe_target("plans")
        if not plans_dir.exists():
            return False
        known = {plan.candidate.id: plan for plan in run.plans}
        recovered = False
        for plan_path in sorted(plans_dir.glob("*/plan.yaml")):
            self._ensure_safe_path(plan_path)
            try:
                raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("plan.yaml must contain a mapping")
                plan = PlanRecord.from_dict(_safe_value(raw))
            except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Unable to load plan record {plan_path.parent.name}: "
                    f"{exc}"
                ) from exc
            target = known.get(plan.candidate.id)
            if target is None:
                target = plan
                run.plans.append(target)
                known[target.candidate.id] = target
                recovered = True
            else:
                merged = _merge_plan(target, plan)
                if merged.to_dict() != target.to_dict():
                    self._replace_plan(run, merged)
                    known[merged.candidate.id] = merged
                    target = merged
                    recovered = True
            if self._recover_attempt_files_locked(plan_path.parent, target):
                recovered = True
            if recovered:
                self._atomic_yaml_locked(plan_path, target.to_dict())
        return recovered

    def _recover_attempt_files_locked(
        self,
        plan_dir: Path,
        plan: PlanRecord,
    ) -> bool:
        attempts_dir = plan_dir / "attempts"
        if not attempts_dir.exists():
            return False
        self._ensure_safe_path(attempts_dir)
        recovered = False
        for attempt_dir in sorted(attempts_dir.iterdir()):
            self._ensure_safe_path(attempt_dir)
            if not attempt_dir.is_dir():
                continue
            try:
                attempt_no = int(attempt_dir.name)
            except ValueError as exc:
                raise ValueError(
                    f"Unable to load attempt record {attempt_dir}: "
                    "attempt directory must be numeric"
                ) from exc
            existing = next(
                (
                    attempt
                    for attempt in plan.attempts
                    if attempt.number == attempt_no
                ),
                None,
            )
            attempt_path = attempt_dir / "attempt.yaml"
            if attempt_path.exists():
                child = self._load_attempt_file_locked(attempt_path)
                merged = _merge_attempts(
                    [existing] if existing else [],
                    [child],
                )[0]
            elif existing is not None:
                merged = existing
            else:
                raise ValueError(
                    f"Unable to load attempt record {attempt_dir}: "
                    "attempt.yaml is missing"
                )

            review_path = attempt_dir / "review.json"
            if review_path.exists():
                review = self._load_review_file_locked(review_path)
                merged.review = review

            if existing is None or merged.to_dict() != existing.to_dict():
                plan.attempts = _merge_attempts(plan.attempts, [merged])
                recovered = True
            if recovered:
                self._atomic_yaml_locked(
                    attempt_path,
                    self._find_attempt(plan, attempt_no).to_dict(),
                )
        return recovered

    def _load_attempt_file_locked(self, path: Path) -> AttemptRecord:
        self._ensure_safe_path(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("attempt.yaml must contain a mapping")
            return AttemptRecord.from_dict(_safe_value(raw))
        except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Unable to load attempt record {path}: {exc}"
            ) from exc

    def _load_review_file_locked(self, path: Path) -> ReviewResult:
        self._ensure_safe_path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("review.json must contain an object")
            return ReviewResult.from_dict(_safe_value(raw))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Unable to load review record {path}: {exc}"
            ) from exc

    def _append_event_locked(self, encoded: bytes) -> None:
        path = self._safe_target("events.jsonl")
        descriptor = os.open(
            path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise OSError("Unable to append optimize event")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _find_plan_in(
        run: RunRecord,
        item_id: str,
        *,
        required: bool = True,
    ) -> PlanRecord | None:
        for plan in run.plans:
            if plan.candidate.id == item_id:
                return plan
        if required:
            raise ValueError(f"Unknown item_id: {item_id!r}")
        return None

    @staticmethod
    def _replace_plan(run: RunRecord, plan: PlanRecord) -> None:
        for index, existing in enumerate(run.plans):
            if existing.candidate.id == plan.candidate.id:
                run.plans[index] = plan
                return
        run.plans.append(plan)

    @staticmethod
    def _find_attempt(plan: PlanRecord, attempt_no: int) -> AttemptRecord:
        for attempt in plan.attempts:
            if attempt.number == attempt_no:
                return attempt
        raise ValueError(
            f"Unknown attempt {attempt_no} for item_id "
            f"{plan.candidate.id!r}"
        )

    def _sync_attempt_locked(
        self,
        run: RunRecord,
        plan: PlanRecord,
        attempt: AttemptRecord,
    ) -> None:
        self._atomic_yaml_locked(
            self._attempt_dir(plan.candidate.id, attempt.number)
            / "attempt.yaml",
            attempt.to_dict(),
        )
        self._sync_plan_locked(run, plan)

    def _sync_plan_locked(self, run: RunRecord, plan: PlanRecord) -> None:
        self._atomic_yaml_locked(
            self._plan_dir(plan.candidate.id) / "plan.yaml",
            plan.to_dict(),
        )
        self._write_plan_indexes_locked(plan)
        self._save_state_locked(run)

    def _write_plan_indexes_locked(self, plan: PlanRecord) -> None:
        plan_dir = self._plan_dir(plan.candidate.id)
        self._atomic_yaml_locked(
            plan_dir / "metadata.yaml",
            plan.candidate.to_dict(),
        )
        state = plan.to_dict()
        state.pop("candidate", None)
        state.pop("attempts", None)
        self._atomic_yaml_locked(plan_dir / "state.yaml", state)
        attempts_jsonl = "".join(
            json.dumps(
                _safe_value(attempt.to_dict()), ensure_ascii=False
            ) + "\n"
            for attempt in plan.attempts
        )
        self._atomic_text_locked(
            plan_dir / "attempts.jsonl", attempts_jsonl
        )
