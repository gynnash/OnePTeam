"""Tests for optimize run records and their serialization contract."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from onep.strategy.optimize_models import (
    AttemptRecord,
    FailureReason,
    PlanCandidate,
    PlanRecord,
    PlanStatus,
    ReviewResult,
    RunRecord,
    RunStatus,
    TestCommandResult,
)

EXPECTED_ALLOWED_TRANSITIONS = {
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
        PlanStatus.BRANCH_CREATED,
        PlanStatus.FAILED,
        PlanStatus.SKIPPED,
    },
    PlanStatus.BRANCH_CREATED: {
        PlanStatus.DEVELOPING,
        PlanStatus.FAILED,
    },
    PlanStatus.DEVELOPING: {
        PlanStatus.TESTING,
        PlanStatus.FAILED,
    },
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
        PlanStatus.DEVELOPING,
        PlanStatus.TESTING,
        PlanStatus.FAILED,
    },
    PlanStatus.PASSED: {
        PlanStatus.COMMITTED,
        PlanStatus.FAILED,
    },
    PlanStatus.COMMITTED: {
        PlanStatus.INTEGRATING,
        PlanStatus.INTEGRATED,
        PlanStatus.FAILED,
    },
    PlanStatus.INTEGRATING: {
        PlanStatus.INTEGRATED,
        PlanStatus.FAILED,
    },
    PlanStatus.FAILED: {PlanStatus.ROLLED_BACK},
    PlanStatus.INTEGRATED: set(),
    PlanStatus.ROLLED_BACK: set(),
    PlanStatus.SKIPPED: set(),
}

ALLOWED_TRANSITION_CASES = [
    (start, target)
    for start, targets in EXPECTED_ALLOWED_TRANSITIONS.items()
    for target in targets
]

FORBIDDEN_TRANSITION_CASES = [
    (start, target)
    for start, allowed_targets in EXPECTED_ALLOWED_TRANSITIONS.items()
    for target in PlanStatus
    if target is not start and target not in allowed_targets
]


def test_enum_values_serialize_as_stable_strings() -> None:
    candidate = PlanCandidate(
        id="plan-models",
        title="Add optimize models",
        summary="Persist coordinator state",
        files={Path("onep/strategy/optimize_models.py")},
        dependencies={"plan-foundation"},
        test_commands=("pytest tests/test_strategy/test_optimize_models.py",),
    )
    plan = PlanRecord(candidate=candidate, status=PlanStatus.PLANNED)
    run = RunRecord(
        id="run-001",
        project_name="onep",
        source_path=Path("/tmp/onep"),
        status=RunStatus.RUNNING,
        plans=[plan],
    )

    payload = run.to_dict()

    assert payload["status"] == "running"
    assert payload["plans"][0]["status"] == "planned"
    assert payload["plans"][0]["candidate"]["files"] == [
        "onep/strategy/optimize_models.py"
    ]
    assert payload["plans"][0]["candidate"]["dependencies"] == [
        "plan-foundation"
    ]
    json.dumps(payload)


def test_plan_records_terminal_failure_reason_and_details() -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=PlanStatus.REPAIRING,
    )

    plan.fail(
        FailureReason.FIX_ATTEMPTS_EXHAUSTED,
        "Review still reports unsafe rollback after three attempts",
    )
    plan.transition_to(PlanStatus.ROLLED_BACK)

    assert plan.status is PlanStatus.ROLLED_BACK
    assert plan.failure_reason is FailureReason.FIX_ATTEMPTS_EXHAUSTED
    assert "three attempts" in plan.failure_detail
    assert PlanRecord.from_dict(plan.to_dict()) == plan


def test_fail_normalizes_valid_failure_reason_string() -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=PlanStatus.TESTING,
    )

    plan.fail("test_failed", "pytest failed")

    assert plan.failure_reason is FailureReason.TEST_FAILED
    assert plan.to_dict()["failure_reason"] == "test_failed"


def test_fail_rejects_unknown_failure_reason_without_changing_plan() -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=PlanStatus.TESTING,
    )

    with pytest.raises(ValueError, match="failure_reason"):
        plan.fail("unknown")

    assert plan.status is PlanStatus.TESTING
    assert plan.failure_reason is None


def test_attempt_record_round_trip_preserves_execution_evidence() -> None:
    attempt = AttemptRecord(
        number=2,
        branch="onep/optimize/plan-a",
        base_commit="abc123",
        changed_files={
            Path("onep/strategy/optimize_models.py"),
            Path("tests/test_strategy/test_optimize_models.py"),
        },
        test_results=[
            TestCommandResult(
                command="pytest tests/test_strategy/test_optimize_models.py -q",
                exit_code=1,
                stdout="1 failed",
                stderr="",
                duration_seconds=0.42,
            )
        ],
        review=ReviewResult(
            passed=False,
            summary="Transition validation is incomplete",
            findings=["Terminal states can move backwards"],
        ),
        cost=0.125,
        feedback=["Reject transitions out of terminal states"],
        artifacts={
            "test_log": Path("/tmp/run-001/plan-a/attempt-2/tests.log"),
            "metrics": {"failed": 1},
        },
    )

    restored = AttemptRecord.from_dict(attempt.to_dict())

    assert restored == attempt
    json.dumps(attempt.to_dict())


def test_run_record_retains_successful_and_failed_plans_without_worktrees() -> None:
    successful = PlanRecord(
        candidate=PlanCandidate(id="success", title="Successful plan"),
        status=PlanStatus.INTEGRATED,
        branch="onep/optimize/success",
        commit_sha="def456",
    )
    failed = PlanRecord(
        candidate=PlanCandidate(id="failure", title="Failed plan"),
        status=PlanStatus.FAILED,
        branch="onep/optimize/failure",
        failure_reason=FailureReason.TEST_FAILED,
        failure_detail="pytest exited with status 1",
    )
    run = RunRecord(
        id="run-001",
        project_name="onep",
        source_path=Path("/deleted/source/worktree"),
        status=RunStatus.PARTIAL,
        plans=[successful, failed],
        total_cost=1.75,
    )

    restored = RunRecord.from_dict(run.to_dict())

    assert restored == run
    assert [plan.candidate.id for plan in restored.plans] == ["success", "failure"]
    assert restored.plans[1].failure_reason is FailureReason.TEST_FAILED


def test_all_coordinator_states_and_failure_reasons_are_available() -> None:
    assert {status.value for status in PlanStatus} >= {
        "pending",
        "planned",
        "developing",
        "testing",
        "reviewing",
        "repairing",
        "committed",
        "integrated",
        "failed",
        "rolled_back",
        "skipped",
    }
    assert {reason.value for reason in FailureReason} >= {
        "no_changes",
        "test_failed",
        "review_failed",
        "fix_attempts_exhausted",
        "budget_exhausted",
        "cherry_pick_conflict",
        "integration_test_failed",
        "internal_error",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),
        ("TRUE", True),
        ("FALSE", False),
    ],
)
def test_review_result_strictly_parses_boolean_values(
    raw: object,
    expected: bool,
) -> None:
    assert ReviewResult.from_dict({"passed": raw}).passed is expected


@pytest.mark.parametrize("raw", ["yes", "0", 0, 1, None, [], {}])
def test_review_result_rejects_ambiguous_boolean_values(raw: object) -> None:
    with pytest.raises(ValueError, match="passed"):
        ReviewResult.from_dict({"passed": raw})


def test_from_dict_normalizes_null_containers_and_optional_values() -> None:
    attempt = AttemptRecord.from_dict(
        {
            "number": 1,
            "branch": "onep/optimize/nulls",
            "base_commit": "abc123",
            "changed_files": None,
            "test_results": None,
            "review": None,
            "feedback": None,
            "artifacts": None,
        }
    )
    plan = PlanRecord.from_dict(
        {
            "candidate": {
                "id": "nulls",
                "title": "Null containers",
                "summary": None,
                "files": None,
                "dependencies": None,
                "test_commands": None,
            },
            "status": None,
            "attempts": None,
            "failure_reason": None,
            "artifacts": None,
        }
    )
    run = RunRecord.from_dict(
        {
            "id": "run-null",
            "project_name": "onep",
            "source_path": "/tmp/onep",
            "status": None,
            "plans": None,
            "artifacts": None,
        }
    )

    assert attempt.changed_files == set()
    assert attempt.test_results == []
    assert attempt.review is None
    assert attempt.feedback == []
    assert attempt.artifacts == {}
    assert plan.candidate.summary == ""
    assert plan.candidate.files == set()
    assert plan.candidate.dependencies == set()
    assert plan.candidate.test_commands == ()
    assert plan.status is PlanStatus.PENDING
    assert plan.failure_reason is None
    assert plan.attempts == []
    assert run.status is RunStatus.PENDING
    assert run.plans == []


@pytest.mark.parametrize(
    ("factory", "payload", "field"),
    [
        (ReviewResult.from_dict, {}, "passed"),
        (
            TestCommandResult.from_dict,
            {"command": None, "exit_code": 0},
            "command",
        ),
        (
            AttemptRecord.from_dict,
            {"number": 1, "branch": None, "base_commit": "abc"},
            "branch",
        ),
        (
            PlanCandidate.from_dict,
            {"id": None, "title": "Plan"},
            "id",
        ),
        (
            PlanRecord.from_dict,
            {"candidate": None},
            "candidate",
        ),
        (
            RunRecord.from_dict,
            {"id": "run", "project_name": "onep", "source_path": None},
            "source_path",
        ),
    ],
)
def test_from_dict_rejects_missing_or_null_required_fields(
    factory: object,
    payload: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValueError, match=field):
        factory(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("start", "target"),
    ALLOWED_TRANSITION_CASES,
)
def test_state_machine_accepts_all_expected_allowed_edges(
    start: PlanStatus,
    target: PlanStatus,
) -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=start,
    )

    plan.transition_to(target)

    assert plan.status is target


@pytest.mark.parametrize(
    ("start", "target"),
    FORBIDDEN_TRANSITION_CASES,
)
def test_state_machine_rejects_all_other_edges(
    start: PlanStatus,
    target: PlanStatus,
) -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=start,
    )

    with pytest.raises(ValueError, match=rf"{start.value}.*{target.value}"):
        plan.transition_to(target)


def test_plan_status_is_normalized_for_construction_and_transition() -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status="planned",  # type: ignore[arg-type]
    )

    assert plan.status is PlanStatus.PLANNED
    plan.transition_to("developing")  # type: ignore[arg-type]
    assert plan.status is PlanStatus.DEVELOPING


@pytest.mark.parametrize("status", list(PlanStatus))
def test_repeated_transition_is_a_no_op(status: PlanStatus) -> None:
    plan = PlanRecord(
        candidate=PlanCandidate(id="plan-a", title="Plan A"),
        status=status,
    )

    plan.transition_to(status.value)

    assert plan.status is status


@pytest.mark.parametrize("raw", ["unknown", "", None, 7])
def test_plan_rejects_unknown_status_values(raw: object) -> None:
    with pytest.raises(ValueError, match="status"):
        PlanRecord(
            candidate=PlanCandidate(id="plan-a", title="Plan A"),
            status=raw,  # type: ignore[arg-type]
        )


def test_from_dict_rejects_unknown_enum_values() -> None:
    with pytest.raises(ValueError, match="status"):
        RunRecord.from_dict(
            {
                "id": "run",
                "project_name": "onep",
                "source_path": "/tmp/onep",
                "status": "unknown",
            }
        )
    with pytest.raises(ValueError, match="failure_reason"):
        PlanRecord.from_dict(
            {
                "candidate": {"id": "plan", "title": "Plan"},
                "failure_reason": "unknown",
            }
        )
