from pathlib import Path
from types import SimpleNamespace

import git

from onep.cli.optimize_cmd import _render_run_report
from onep.strategy.git_session import GitRunSession
from onep.strategy.optimize_coordinator import OptimizeCoordinator
from onep.strategy.optimize_models import (
    PlanCandidate,
    ReviewResult,
    RunRecord,
    RunStatus,
    TestCommandResult,
)
from onep.strategy.optimize_recorder import OptimizeRunRecorder
from onep.strategy.test_runner import PlanTestResult


def _repository(path):
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "OneP Smoke")
        config.set_value("user", "email", "onep@example.com")
    (path / "app.py").write_text("base\n")
    repo.index.add(["app.py"])
    repo.index.commit("initial")
    return repo


class WritingEngine:
    def execute_attempt(self, **kwargs):
        path = Path(kwargs["source_path"]) / "app.py"
        path.write_text(path.read_text() + "success\n")
        return SimpleNamespace(output="implemented")


class PassingReview:
    def review(self, *args):
        return ReviewResult(True, "ok")


class ConstantTests:
    def __init__(self, passed):
        self.passed = passed

    def run(self, *args):
        return PlanTestResult([
            TestCommandResult("test", 0 if self.passed else 1)
        ])


def test_real_git_run_keeps_success_and_failure_history(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = _repository(source)
    original_head = repo.head.commit.hexsha
    run_dir = tmp_path / "run"
    git_session = GitRunSession(source, run_dir, "smoke")
    integration_branch = git_session.create_integration_branch()
    run = RunRecord(
        "smoke", "demo", source, RunStatus.RUNNING,
        base_commit=original_head,
        integration_branch=integration_branch,
    )
    recorder = OptimizeRunRecorder(run_dir, run)

    success = OptimizeCoordinator(
        WritingEngine(), ConstantTests(True), PassingReview(),
        git_session, recorder=recorder,
    ).execute_plan(
        PlanCandidate("success", "Success", files={Path("app.py")},
                      test_commands=("test",)),
        "# success",
    )
    failed = OptimizeCoordinator(
        WritingEngine(), ConstantTests(False), PassingReview(),
        git_session, recorder=recorder,
    ).execute_plan(
        PlanCandidate("failure", "Failure", files={Path("app.py")},
                      test_commands=("test",)),
        "# failure",
    )

    assert success.commit_sha
    assert failed.failure_reason.value == "fix_attempts_exhausted"
    assert failed.branch not in [head.name for head in repo.heads]
    assert repo.head.commit.hexsha == original_head
    assert (source / "app.py").read_text() == "base\n"
    assert (git_session.integration_worktree / "app.py").read_text() == (
        "base\nsuccess\n"
    )
    persisted = OptimizeRunRecorder.load(run_dir).run
    report = _render_run_report(persisted)
    assert "[integrated] Success" in report
    assert "[rolled_back] Failure" in report
    assert "fix_attempts_exhausted" in report
