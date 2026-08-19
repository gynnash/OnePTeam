"""Human intervention channel for the harness.

The harness never waits on humans; humans write decisions to
`<workspace>/.onep/harness/candidate-decisions.jsonl` and the engine applies
them at the next PRIORITIZE boundary. The web console writes through the
documented REST endpoints; the engine applies through apply_candidate_decisions.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from onep.harness.models import HarnessRun, ImprovementCandidate
from onep.harness.scorer import classify

VALID_DECISIONS = ("approve", "reject", "rescore")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidate_decisions_path(workspace: Path) -> Path:
    return Path(workspace) / ".onep" / "harness" / "candidate-decisions.jsonl"


def stop_request_path(workspace: Path) -> Path:
    return Path(workspace) / ".onep" / "harness" / "stop_requested"


def request_stop(workspace: Path) -> None:
    """Write the stop flag the engine polls at each PLAN boundary."""
    path = stop_request_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"requested_at": _now(), "source": "web"}) + "\n", encoding="utf-8"
    )


def load_candidate_decisions(workspace: Path) -> list[dict[str, Any]]:
    """All recorded decisions, oldest first. Invalid lines are skipped."""
    path = candidate_decisions_path(workspace)
    if not path.exists():
        return []
    decisions: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            decisions.append(entry)
    return decisions


def save_candidate_decisions(workspace: Path, decisions: list[dict[str, Any]]) -> None:
    """Atomic rewrite of the decisions file (append + replace)."""
    path = candidate_decisions_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix="candidate-decisions-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temp:
            for entry in decisions:
                temp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def record_candidate_decision(
    workspace: Path,
    candidate_id: str,
    decision: str,
    score: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append one human decision. Returns the stored entry."""
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"invalid decision {decision!r}; expected one of {VALID_DECISIONS}"
        )
    if decision == "rescore":
        if score is None:
            raise ValueError("rescore requires a score")
        score = min(1.0, max(0.0, float(score)))
    entry: dict[str, Any] = {
        "candidate_id": candidate_id,
        "decision": decision,
        "applied": False,
        "note": note,
        "created_at": _now(),
    }
    if score is not None:
        entry["score"] = score
    decisions = load_candidate_decisions(workspace)
    decisions.append(entry)
    save_candidate_decisions(workspace, decisions)
    return entry


def merged_candidates(run: HarnessRun, workspace: Path) -> list[dict[str, Any]]:
    """Run candidates with the latest matching decision attached."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in load_candidate_decisions(workspace):
        latest[entry.get("candidate_id", "")] = entry
    rows = []
    for candidate in run.improvement_candidates:
        row = candidate.to_dict()
        entry = latest.get(candidate.id)
        row["decision"] = (
            {
                key: entry.get(key)
                for key in ("decision", "score", "note", "applied", "created_at")
            }
            if entry is not None
            else None
        )
        rows.append(row)
    return rows


def apply_candidate_decisions(
    run: HarnessRun,
    workspace: Path,
    backlog: list[ImprovementCandidate],
    parked: list[ImprovementCandidate],
) -> tuple[list[ImprovementCandidate], list[ImprovementCandidate]]:
    """Apply unapplied human decisions to this round's candidates.

    approve -> move the candidate into the backlog (it will be built).
    reject -> park the candidate (visible, never built).
    rescore -> re-score with the human score, then reclassify.
    Decisions naming candidates absent from this round's lists stay pending.
    """
    decisions = load_candidate_decisions(workspace)
    unapplied = [entry for entry in decisions if not entry.get("applied")]
    if not unapplied:
        return backlog, parked
    by_id = {candidate.id: candidate for candidate in backlog}
    by_id.update({candidate.id: candidate for candidate in parked})
    changed = False
    for entry in unapplied:
        candidate = by_id.get(entry.get("candidate_id", ""))
        if candidate is None:
            continue
        entry["applied"] = True
        changed = True
        if entry.get("decision") == "approve":
            candidate.status = "backlog"
            if not any(existing is candidate for existing in backlog):
                backlog.append(candidate)
            parked = [c for c in parked if c is not candidate]
        elif entry.get("decision") == "reject":
            candidate.status = "rejected"
            backlog = [c for c in backlog if c is not candidate]
            parked = [c for c in parked if c is not candidate]
        elif entry.get("decision") == "rescore":
            score = entry.get("score")
            if score is not None:
                candidate.score = float(score)
            candidate.status = classify(candidate.score)
            if candidate.status == "backlog":
                if not any(existing is candidate for existing in backlog):
                    backlog.append(candidate)
                parked = [c for c in parked if c is not candidate]
            else:
                backlog = [c for c in backlog if c is not candidate]
                if not any(existing is candidate for existing in parked):
                    parked.append(candidate)
    if changed:
        save_candidate_decisions(workspace, decisions)
    return backlog, parked
