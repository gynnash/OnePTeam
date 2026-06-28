from pathlib import Path
from types import SimpleNamespace

import git

from onep.strategy.optimize_coordinator import OptimizeCoordinator
from onep.strategy.optimize_models import (
    PlanCandidate,
    PlanStatus,
    ReviewResult,
    TestCommandResult,
)
from onep.strategy.test_runner import PlanTestResult


class FakePlan:
    branch_name = "onep/plan-si-1"
    base_commit = "base"
    worktree = Path("/tmp/plan")

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.removes = 0
        self.changed = ["app.py"]

    def changed_files(self):
        return self.changed

    def diff(self):
        return "diff"

    def commit(self, message):
        self.commits += 1
        return "commit"

    def rollback(self):
        self.rollbacks += 1

    def remove(self, delete_branch):
        self.removes += 1


class FakeGit:
    def __init__(self):
        self.plan = FakePlan()
        self.integrated = []
        self.integration_worktree = Path("/tmp/integration")

    def create_plan_session(self, item_id, slug):
        return self.plan

    def integrate(self, commit):
        self.integrated.append(commit)
        return "integrated"

    def abort_cherry_pick(self):
        self.aborted = True


class FakeEngine:
    def __init__(self):
        self.feedback = []

    def execute_attempt(self, **kwargs):
        self.feedback.append(kwargs["feedback"])
        return SimpleNamespace(output="done")


class Sequence:
    def __init__(self, values):
        self.values = iter(values)

    def run(self, *args):
        return next(self.values)

    def review(self, *args):
        return next(self.values)


def _tests(passed):
    code = 0 if passed else 1
    return PlanTestResult([TestCommandResult("pytest", code)])


def _candidate():
    return PlanCandidate(
        id="si-1", title="Cache", files={Path("app.py")},
        test_commands=("pytest",),
    )


def test_review_failure_is_repaired_on_same_branch():
    git = FakeGit()
    engine = FakeEngine()
    coordinator = OptimizeCoordinator(
        engine=engine,
        test_runner=Sequence([_tests(True), _tests(True), _tests(True)]),
        reviewer=Sequence([
            ReviewResult(False, "race", ["app.py:1: race"]),
            ReviewResult(True, "ok"),
        ]),
        git_session=git,
        max_attempts=3,
    )

    result = coordinator.execute_plan(_candidate(), "# plan")

    assert result.status == PlanStatus.INTEGRATED
    assert engine.feedback == ["", "app.py:1: race"]
    assert git.plan.commits == 1
    assert git.integrated == ["commit"]


def test_three_test_failures_roll_back_without_commit():
    git = FakeGit()
    coordinator = OptimizeCoordinator(
        engine=FakeEngine(),
        test_runner=Sequence([_tests(False)] * 3),
        reviewer=Sequence([]),
        git_session=git,
        max_attempts=3,
    )
    result = coordinator.execute_plan(_candidate(), "# plan")
    assert result.status == PlanStatus.ROLLED_BACK
    assert result.failure_reason.value == "fix_attempts_exhausted"
    assert len(result.attempts) == 3
    assert git.plan.commits == 0
    assert git.plan.rollbacks == 1
    assert git.plan.removes == 1


class FakeRecorder:
    def __init__(self):
        self.attempts = []
        self.reviews = []
        self.tests = []
        self.events = []

    def record_event(self, name, payload):
        self.events.append((name, payload))

    def save_plan(self, *args):
        pass

    def save_diff(self, *args):
        pass

    def save_attempt(self, item_id, attempt):
        self.attempts.append((item_id, attempt.number))

    def save_review(self, item_id, number, review):
        self.reviews.append((item_id, number, review.passed))

    def save_test_output(self, item_id, number, output):
        self.tests.append((item_id, number, output))


def test_each_attempt_writes_test_and_review_artifacts():
    recorder = FakeRecorder()
    coordinator = OptimizeCoordinator(
        engine=FakeEngine(),
        test_runner=Sequence([_tests(True), _tests(True)]),
        reviewer=Sequence([ReviewResult(True, "ok")]),
        git_session=FakeGit(),
        recorder=recorder,
    )
    result = coordinator.execute_plan(_candidate(), "# plan")
    assert result.status == PlanStatus.INTEGRATED
    assert recorder.attempts == [("si-1", 1)]
    assert recorder.reviews == [("si-1", 1, True)]
    assert recorder.tests[0][:2] == ("si-1", 1)


def test_cherry_pick_conflict_rolls_back_only_current_plan():
    git_session = FakeGit()

    def conflict(_commit):
        raise git.GitCommandError("cherry-pick", 1, stderr="conflict")

    git_session.integrate = conflict
    coordinator = OptimizeCoordinator(
        engine=FakeEngine(),
        test_runner=Sequence([_tests(True)]),
        reviewer=Sequence([ReviewResult(True, "ok")]),
        git_session=git_session,
    )
    result = coordinator.execute_plan(_candidate(), "# plan")
    assert result.status == PlanStatus.ROLLED_BACK
    assert result.failure_reason.value == "cherry_pick_conflict"
    assert git_session.plan.rollbacks == 1
    assert git_session.plan.removes == 1


class RejectingBudget:
    def can_continue(self):
        return True

    def reserve(self, amount):
        return False


def test_budget_reservation_prevents_llm_call():
    engine = FakeEngine()
    result = OptimizeCoordinator(
        engine=engine,
        test_runner=Sequence([]),
        reviewer=Sequence([]),
        git_session=FakeGit(),
        cost_tracker=RejectingBudget(),
        llm_reservation=0.1,
    ).execute_plan(_candidate(), "# plan")
    assert result.status == PlanStatus.ROLLED_BACK
    assert result.failure_reason.value == "budget_exhausted"
    assert engine.feedback == []


def test_develop_plan_stops_at_commit_before_integration():
    git_session = FakeGit()
    session = git_session.plan
    result = OptimizeCoordinator(
        engine=FakeEngine(),
        test_runner=Sequence([_tests(True)]),
        reviewer=Sequence([ReviewResult(True, "ok")]),
        git_session=git_session,
    ).develop_plan(_candidate(), "# plan", session)
    assert result.status == PlanStatus.COMMITTED
    assert git_session.integrated == []
