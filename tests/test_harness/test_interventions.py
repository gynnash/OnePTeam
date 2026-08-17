import json
from pathlib import Path

import pytest

from onep.harness.interventions import (
    apply_candidate_decisions, candidate_decisions_path,
    load_candidate_decisions, merged_candidates,
    record_candidate_decision, request_stop, stop_request_path,
)
from onep.harness.models import HarnessRun, HarnessOptions, ImprovementCandidate


def _run(tmp_path):
    return HarnessRun(id="h-1", project_name="demo", workspace=str(tmp_path),
                      mode="greenfield", original_goal="build value",
                      options=HarnessOptions(max_rounds=4))


def test_request_stop_writes_flag(tmp_path):
    request_stop(tmp_path)
    assert stop_request_path(tmp_path).exists()
    entry = json.loads(stop_request_path(tmp_path).read_text())
    assert entry["source"] == "web"


def test_record_and_load_decisions(tmp_path):
    entry = record_candidate_decision(tmp_path, "I-001", "approve", note="ship it")
    assert entry["decision"] == "approve"
    assert entry["applied"] is False
    entries = load_candidate_decisions(tmp_path)
    assert len(entries) == 1
    assert entries[0]["candidate_id"] == "I-001"
    assert entries[0]["note"] == "ship it"


def test_record_rescore_clamps_score(tmp_path):
    entry = record_candidate_decision(tmp_path, "I-001", "rescore", score=1.7)
    assert entry["score"] == 1.0
    with pytest.raises(ValueError):
        record_candidate_decision(tmp_path, "I-001", "rescore")
    with pytest.raises(ValueError):
        record_candidate_decision(tmp_path, "I-001", "maybe")


def test_apply_approve_moves_to_backlog(tmp_path):
    run = _run(tmp_path)
    record_candidate_decision(tmp_path, "I-001", "approve", note="user wants it")
    candidate = ImprovementCandidate(id="I-001", title="Add CLI", score=0.5, status="parked")
    backlog, parked = apply_candidate_decisions(run, tmp_path, [], [candidate])
    assert backlog == [candidate]
    assert parked == []
    assert candidate.status == "backlog"
    assert load_candidate_decisions(tmp_path)[0]["applied"] is True


def test_apply_reject_parks(tmp_path):
    run = _run(tmp_path)
    record_candidate_decision(tmp_path, "I-001", "reject")
    candidate = ImprovementCandidate(id="I-001", title="Add CLI", score=0.8, status="backlog")
    backlog, parked = apply_candidate_decisions(run, tmp_path, [candidate], [])
    assert backlog == []
    assert candidate.status == "rejected"


def test_apply_rescore_reclassifies(tmp_path):
    run = _run(tmp_path)
    record_candidate_decision(tmp_path, "I-001", "rescore", score=0.9)
    candidate = ImprovementCandidate(id="I-001", title="Add CLI", score=0.5, status="parked")
    backlog, parked = apply_candidate_decisions(run, tmp_path, [], [candidate])
    assert candidate.status == "backlog"  # 0.9 > 0.75
    assert backlog == [candidate]


def test_apply_unknown_candidate_stays_pending(tmp_path):
    run = _run(tmp_path)
    record_candidate_decision(tmp_path, "I-999", "approve")
    candidate = ImprovementCandidate(id="I-001", title="Add CLI", score=0.5, status="parked")
    backlog, parked = apply_candidate_decisions(run, tmp_path, [], [candidate])
    assert parked == [candidate]
    assert load_candidate_decisions(tmp_path)[0]["applied"] is False


def test_apply_noop_without_decisions(tmp_path):
    run = _run(tmp_path)
    candidate = ImprovementCandidate(id="I-001", title="Add CLI", score=0.5, status="parked")
    backlog, parked = apply_candidate_decisions(run, tmp_path, [], [candidate])
    assert (backlog, parked) == ([], [candidate])


def test_merged_candidates_attaches_latest_decision(tmp_path):
    run = _run(tmp_path)
    run.improvement_candidates = [
        ImprovementCandidate(id="I-001", title="Add CLI", score=0.5, status="parked"),
    ]
    record_candidate_decision(tmp_path, "I-001", "approve", note="yep")
    rows = merged_candidates(run, tmp_path)
    assert rows[0]["decision"]["decision"] == "approve"
    assert rows[0]["decision"]["applied"] is False
