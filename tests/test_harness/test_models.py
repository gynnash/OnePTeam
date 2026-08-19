from pathlib import Path

from onep.greenfield.models import GreenfieldOptions, GreenfieldRun, SlicePlan
from onep.harness.models import (
    CandidateAdapter,
    HarnessOptions,
    HarnessRun,
    ImprovementCandidate,
    QualitySnapshot,
    SliceAdapter,
    StopDecision,
    StopReason,
    WorkItem,
    candidate_to_slice,
)
from onep.strategy.optimize_models import PlanCandidate


def test_slice_adapter_round_trip():
    plan = SlicePlan(
        id="slice-1", title="Core", objective="set value",
        acceptance_ids=["REQ-1"], expected_files=["app.py", "test_app.py"],
        focused_commands=["pytest -q"], status="completed",
        attempts=2, commit_sha="abc123",
    )
    item = SliceAdapter.to_work_item(plan)
    assert item.source == "slice"
    assert item.id == "slice-1"
    assert item.expected_files == ["app.py", "test_app.py"]
    assert item.attempts == 2
    back = SliceAdapter.to_slice_plan(item, index=0)
    assert back.id == plan.id
    assert back.title == plan.title
    assert back.objective == plan.objective
    assert back.acceptance_ids == plan.acceptance_ids
    assert back.focused_commands == plan.focused_commands
    assert back.status == "completed"
    assert back.commit_sha == "abc123"


def test_candidate_adapter_round_trip():
    candidate = PlanCandidate(
        id="plan-1", title="Fix auth", summary="auth is broken",
        files={Path("auth.py")}, focused_test_commands=("pytest -q",),
        fingerprint="fp-1",
    )
    item = CandidateAdapter.to_work_item(candidate)
    assert item.source == "candidate"
    assert item.fingerprint == "fp-1"
    assert item.expected_files == ["auth.py"]
    back = CandidateAdapter.to_plan_candidate(item)
    assert back.id == "plan-1"
    assert back.title == "Fix auth"
    assert back.summary == "auth is broken"
    assert back.files == {Path("auth.py")}
    assert back.fingerprint == "fp-1"


def test_candidate_adapter_computes_missing_fingerprint():
    candidate = PlanCandidate(
        id="plan-2", title="Fix cache invalidation", summary="stale reads",
        files={Path("cache.py")},
    )
    item = CandidateAdapter.to_work_item(candidate)
    assert item.fingerprint


def test_candidate_to_slice_generates_iteration_ids():
    candidate = ImprovementCandidate(
        id="I-001", title="Add CLI", description="expose VALUE via CLI",
    )
    plan = candidate_to_slice(candidate, iteration=2, index=0)
    assert plan.id == "iter2-1"
    assert plan.title == "Add CLI"
    assert plan.objective == "expose VALUE via CLI"
    assert plan.acceptance_ids == []
    assert plan.expected_files == []
    assert plan.status == "pending"


def test_harness_run_yaml_round_trip():
    gf_run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="build value",
        workspace="/tmp/demo",
    )
    run = HarnessRun(
        id="h-1", project_name="demo", workspace="/tmp/demo",
        mode="greenfield", original_goal="build value",
        options=HarnessOptions.from_greenfield(
            GreenfieldOptions(max_rounds=7, test_commands=["pytest -q"])
        ),
        greenfield_run=gf_run,
        work_items=[SliceAdapter.to_work_item(SlicePlan(
            id="slice-1", title="Core", objective="set value",
            acceptance_ids=[], expected_files=[],
        ))],
        improvement_candidates=[ImprovementCandidate(
            id="I-001", title="Add CLI", description="...",
            fingerprint="fp-1", status="backlog",
        )],
        quality_history=[QualitySnapshot(
            iteration=1, acceptance_pass_rate=1.0, test_pass_rate=1.0,
            goal_coverage=1.0, quality_score=1.0, hard_gates_passed=True,
        )],
        stop_state={"reason": "goals_satisfied", "evidence": {}},
        iteration=2,
    )
    restored = HarnessRun.from_dict(run.to_dict())
    assert restored.id == "h-1"
    assert restored.options.max_rounds == 7
    assert restored.greenfield_run.id == "gf-1"
    assert restored.work_items[0].title == "Core"
    assert restored.improvement_candidates[0].status == "backlog"
    assert restored.quality_history[0].quality_score == 1.0
    assert restored.stop_state["reason"] == "goals_satisfied"


def test_harness_run_from_dict_tolerates_missing_optional_fields():
    restored = HarnessRun.from_dict({
        "id": "h-2", "project_name": "demo", "workspace": "/tmp",
        "mode": "greenfield", "original_goal": "",
    })
    assert restored.work_items == []
    assert restored.greenfield_run is None
    assert restored.iteration == 0
    assert restored.stage == "init"


def test_stop_decision_defaults():
    decision = StopDecision(stop=False)
    assert decision.reason is None
    assert decision.evidence == {}
    assert StopReason.DIMINISHING_RETURNS.value == "diminishing_returns"


from onep.harness.models import ImprovementCandidate, QualitySnapshot, HarnessRun


def test_improvement_candidate_round_trip_with_score_fields():
    candidate = ImprovementCandidate(
        id="I-1", title="Add caching", description="cache reads",
        score=0.82,
        dimensions={"V": 0.9, "Q": 0.7, "R": 0.5, "E": 0.4, "C": 0.2,
                    "Risk": 0.1, "rationale": "fast wins"},
        evidence="acceptance REQ-3 wants faster reads",
        status="backlog",
    )
    restored = ImprovementCandidate.from_dict(candidate.to_dict())
    assert restored.score == 0.82
    assert restored.dimensions["V"] == 0.9
    assert restored.evidence.startswith("acceptance")
    assert restored.status == "backlog"


def test_improvement_candidate_defaults_for_v1_yaml():
    restored = ImprovementCandidate.from_dict({"id": "I-1", "title": "T"})
    assert restored.score is None
    assert restored.dimensions == {}
    assert restored.evidence == ""


def test_quality_snapshot_round_trip_with_new_fields():
    snapshot = QualitySnapshot(
        iteration=2, acceptance_pass_rate=1.0, test_pass_rate=1.0,
        goal_coverage=0.9, quality_score=0.88, hard_gates_passed=True,
        architecture_quality=0.7, blocker_count=1, risks=["slow startup"],
    )
    restored = QualitySnapshot.from_dict(snapshot.to_dict())
    assert restored.architecture_quality == 0.7
    assert restored.blocker_count == 1
    assert restored.risks == ["slow startup"]


def test_quality_snapshot_v1_yaml_defaults():
    restored = QualitySnapshot.from_dict({
        "iteration": 1, "acceptance_pass_rate": 1.0, "test_pass_rate": 1.0,
        "goal_coverage": 1.0, "quality_score": 1.0,
        "hard_gates_passed": True,
    })
    assert restored.architecture_quality == 0.0
    assert restored.blocker_count == 0
    assert restored.risks == []


def test_harness_run_round_trip_with_research_and_plans():
    run = HarnessRun(
        id="h-1", project_name="demo", workspace="/tmp",
        mode="greenfield", original_goal="build value",
        research_reports=[{"mode": "skipped", "skip_reason": "no repos"}],
        work_item_plans={"item-1": "# plan text"},
    )
    restored = HarnessRun.from_dict(run.to_dict())
    assert restored.research_reports == [{"mode": "skipped",
                                          "skip_reason": "no repos"}]
    assert restored.work_item_plans == {"item-1": "# plan text"}


def test_harness_run_v1_yaml_defaults():
    restored = HarnessRun.from_dict({
        "id": "h-1", "project_name": "demo", "workspace": "/tmp",
        "mode": "greenfield", "original_goal": "",
    })
    assert restored.research_reports == []
    assert restored.work_item_plans == {}


def test_harness_run_round_trip_with_knowledge_events():
    run = HarnessRun(
        id="h-1", project_name="demo", workspace="/tmp",
        mode="greenfield", original_goal="build value",
        knowledge_events=[{
            "type": "decision", "iteration": 1, "problem": "how to wire",
            "selected": "flat", "generalizable": False,
        }],
    )
    restored = HarnessRun.from_dict(run.to_dict())
    assert restored.knowledge_events[0]["type"] == "decision"
    assert restored.knowledge_events[0]["selected"] == "flat"


def test_harness_run_v3_yaml_defaults():
    restored = HarnessRun.from_dict({
        "id": "h-1", "project_name": "demo", "workspace": "/tmp",
        "mode": "greenfield", "original_goal": "",
    })
    assert restored.knowledge_events == []
