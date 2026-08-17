from pathlib import Path

from onep.harness.brownfield import BrownfieldUnderstandStage
from onep.harness.understand import detect_mode


def test_detect_mode_empty_dir_is_greenfield(tmp_path):
    (tmp_path / "readme.md").write_text("# empty\n")
    assert detect_mode(tmp_path, "build a thing") == "greenfield"
    assert detect_mode(tmp_path, "") == "greenfield"


def test_detect_mode_code_without_requirement_is_brownfield(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert detect_mode(tmp_path, "") == "brownfield"
    assert detect_mode(tmp_path, "   ") == "brownfield"


def test_detect_mode_code_with_requirement_is_mixed(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert detect_mode(tmp_path, "add auth") == "mixed"


class ScanLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, system_prompt=None, user_prompt=None, stage_name=None):
        self.calls.append(stage_name)
        return "{}"


def _item():
    from onep.strategy.models import StrategyItem
    return StrategyItem(
        id="si-1", title="Cache", file_location="app.py:1",
        summary="cache issue", tags=["cache"], impact="medium",
    )


def test_brownfield_understand_scans_plans_and_builds_candidates(tmp_path):
    from types import SimpleNamespace

    def fake_analyzer(source, llm, tracker=None, project_name="",
                       source_files=None, **kwargs):
        return [_item()]

    def fake_planner(item, workspace, llm_adapter, plan_index=1,
                     memory_context=""):
        return SimpleNamespace(
            plan_path=str(Path(workspace) / f"{plan_index}.md"),
            plan_markdown=f"# plan {plan_index}",
            expected_files=("cache.py",),
            dependencies=(),
            test_commands=("pytest -q tests/test_cache.py",),
            risk_flags=(),
        )

    stage = BrownfieldUnderstandStage(
        ScanLLM(), analyzer=fake_analyzer, planner=fake_planner,
    )
    candidates, plans = stage.run(
        tmp_path, "demo", ("pytest -q",),
    )
    assert [candidate.id for candidate in candidates] == ["si-1"]
    assert candidates[0].test_commands == ("pytest -q",)
    assert candidates[0].focused_test_commands == (
        "pytest -q tests/test_cache.py",)
    assert plans == {"si-1": "# plan 1"}


from onep.harness.brownfield import BrownfieldBuildStage
from onep.harness.models import CandidateAdapter, WorkItem
from onep.strategy.optimize_models import PlanRecord, PlanStatus


class FakePlanSession:
    def __init__(self, branch_name, worktree, base_commit):
        self.branch_name = branch_name
        self.worktree = worktree
        self.base_commit = base_commit


class FakeGitSession:
    def __init__(self, source_path, run_dir, run_id):
        self.source_path = source_path
        self.created_branches = []

    def create_integration_branch(self):
        self.created_branches.append("integration")
        return "integration"

    def create_plan_session(self, plan_id, title):
        self.created_branches.append(plan_id)
        return FakePlanSession(f"plan-{plan_id}", self.source_path, "c0ffee")


class FakeCoordinator:
    def __init__(self, engine, test_runner, reviewer, git_session,
                 llm=None, recorder=None, cost_tracker=None,
                 project_context="", **kwargs):
        self.git_session = git_session

    def develop_plan(self, candidate, plan_text, session):
        record = PlanRecord(candidate, status=PlanStatus.COMMITTED)
        record.commit_sha = "abc123"
        record.attempts = [
            type("Attempt", (), {"number": 1})()
        ]
        return record

    def integrate_plan(self, record, session, commands):
        record.status = PlanStatus.INTEGRATED
        return record


def test_brownfield_build_develops_and_integrates_each_item(tmp_path):
    sessions = []

    def session_factory(source_path, run_dir, run_id):
        session = FakeGitSession(source_path, run_dir, run_id)
        sessions.append(session)
        return session

    stage = BrownfieldBuildStage(
        tmp_path, tmp_path / "runs" / "r-1", "r-1", object(),
        session_factory=session_factory,
        coordinator_factory=FakeCoordinator,
    )
    from onep.strategy.optimize_models import PlanCandidate
    candidate = PlanCandidate(id="si-1", title="Cache", summary="cache issue")
    item = CandidateAdapter.to_work_item(candidate)
    result = stage.build([item], {"si-1": "# plan"}, ["pytest -q"])

    assert result["integration_passed"] is True
    assert result["items"][0].status == "completed"
    assert result["items"][0].commit_sha == "abc123"
    assert result["items"][0].attempts == 1
    assert len(sessions) == 1
    assert sessions[0].created_branches == ["integration", "si-1"]


def test_brownfield_build_marks_failed_and_unintegrated(tmp_path):
    class FailingCoordinator(FakeCoordinator):
        def develop_plan(self, candidate, plan_text, session):
            return PlanRecord(candidate, status=PlanStatus.FAILED)

    stage = BrownfieldBuildStage(
        tmp_path, tmp_path / "runs" / "r-1", "r-1", object(),
        session_factory=FakeGitSession,
        coordinator_factory=FailingCoordinator,
    )
    from onep.strategy.optimize_models import PlanCandidate
    candidate = PlanCandidate(id="si-1", title="Cache", summary="cache issue")
    item = CandidateAdapter.to_work_item(candidate)
    result = stage.build([item], {"si-1": ""}, ["pytest -q"])

    assert result["integration_passed"] is False
    assert result["items"][0].status == "failed"
    assert result["items"][0].commit_sha == ""


def test_brownfield_build_empty_input_passes(tmp_path):
    stage = BrownfieldBuildStage(
        tmp_path, tmp_path / "runs" / "r-1", "r-1", object(),
        session_factory=FakeGitSession,
        coordinator_factory=FakeCoordinator,
    )
    result = stage.build([], {}, ["pytest -q"])
    assert result["integration_passed"] is True
    assert result["items"] == []
