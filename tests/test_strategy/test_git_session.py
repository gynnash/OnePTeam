from pathlib import Path

import git
import pytest

from onep.strategy.git_session import GitRunSession


def _repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "OneP Test")
        config.set_value("user", "email", "onep@example.com")
    (path / "app.py").write_text("value = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("initial")
    return repo


def test_plan_commit_and_integration_leave_source_checkout_unchanged(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = _repo(source)
    original_head = repo.head.commit.hexsha
    run = GitRunSession(source, tmp_path / "run", "run-1")
    run.create_integration_branch()
    plan = run.create_plan_session("si-1", "cache fix")

    (plan.worktree / "app.py").write_text("value = 2\n")
    assert plan.changed_files() == ["app.py"]
    commit = plan.commit("optimize(si-1): cache fix")

    assert repo.head.commit.hexsha == original_head
    assert (source / "app.py").read_text() == "value = 1\n"
    assert run.integrate(commit) != original_head
    assert (run.integration_worktree / "app.py").read_text() == "value = 2\n"
    with pytest.raises(RuntimeError, match="already committed"):
        plan.commit("second")


def test_rollback_preserves_baseline_untracked_and_ignored(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _repo(source)
    run = GitRunSession(source, tmp_path / "run", "run-2")
    run.create_integration_branch()
    plan = run.create_plan_session("si-2", "rollback")
    (plan.worktree / ".gitignore").write_text("ignored.log\n")
    (plan.worktree / "notes.txt").write_text("keep")
    (plan.worktree / "ignored.log").write_text("keep ignored")
    plan.capture_baseline()
    (plan.worktree / "app.py").write_text("broken\n")
    (plan.worktree / "new").mkdir()
    (plan.worktree / "new" / "generated.py").write_text("remove")

    plan.rollback()

    assert (plan.worktree / "app.py").read_text() == "value = 1\n"
    assert (plan.worktree / "notes.txt").read_text() == "keep"
    assert (plan.worktree / "ignored.log").read_text() == "keep ignored"
    assert not (plan.worktree / "new").exists()


def test_unknown_commit_is_not_integrated(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = _repo(source)
    run = GitRunSession(source, tmp_path / "run", "run-3")
    run.create_integration_branch()

    with pytest.raises(ValueError, match="successful Plan"):
        run.integrate(repo.head.commit.hexsha)


def test_remove_plan_worktree_and_branch_is_idempotent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    repo = _repo(source)
    run = GitRunSession(source, tmp_path / "run", "run-4")
    run.create_integration_branch()
    plan = run.create_plan_session("si-4", "cleanup")
    branch = plan.branch_name

    plan.remove(delete_branch=True)
    plan.remove(delete_branch=True)

    assert not plan.worktree.exists()
    assert branch not in [head.name for head in repo.heads]


def test_cherry_pick_conflict_abort_restores_integration_head(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _repo(source)
    run = GitRunSession(source, tmp_path / "run", "run-conflict")
    run.create_integration_branch()
    first = run.create_plan_session("si-1", "first")
    second = run.create_plan_session("si-2", "second")
    (first.worktree / "app.py").write_text("first\n")
    (second.worktree / "app.py").write_text("second\n")
    first_commit = first.commit("first")
    second_commit = second.commit("second")
    integrated = run.integrate(first_commit)

    with pytest.raises(git.GitCommandError):
        run.integrate(second_commit)
    run.abort_cherry_pick()

    integration_repo = git.Repo(run.integration_worktree)
    assert integration_repo.head.commit.hexsha == integrated
    assert not integration_repo.is_dirty(untracked_files=True)
    assert (run.integration_worktree / "app.py").read_text() == "first\n"


def test_dirty_source_repository_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _repo(source)
    (source / "notes.txt").write_text("dirty")
    with pytest.raises(ValueError, match="dirty"):
        GitRunSession(source, tmp_path / "run", "dirty")


def test_plan_group_uses_one_integration_baseline(tmp_path):
    from types import SimpleNamespace

    source = tmp_path / "source"
    source.mkdir()
    _repo(source)
    run = GitRunSession(source, tmp_path / "run", "group")
    run.create_integration_branch()
    sessions = run.create_plan_group([
        SimpleNamespace(id="a", title="A"),
        SimpleNamespace(id="b", title="B"),
    ])
    assert sessions["a"].base_commit == sessions["b"].base_commit


def test_commit_excludes_baseline_untracked_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _repo(source)
    run = GitRunSession(source, tmp_path / "run", "baseline")
    run.create_integration_branch()
    plan = run.create_plan_session("a", "A")
    (plan.worktree / "keep.txt").write_text("keep")
    plan.capture_baseline()
    (plan.worktree / "app.py").write_text("changed\n")
    commit = plan.commit("change")
    tree = git.Repo(plan.worktree).commit(commit).tree
    assert "keep.txt" not in [item.path for item in tree.traverse()]
