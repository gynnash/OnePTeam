from pathlib import Path

import git
import pytest

from onep.application.task_intent import (
    require_clean_build_worktree,
    require_checked_out_branch,
    resolve_task_intent,
)
from onep.domain import Problem


def _repository(path: Path) -> git.Repo:
    path.mkdir()
    repository = git.Repo.init(path, initial_branch="main")
    (path / "app.py").write_text("print('ready')\n", encoding="utf-8")
    repository.index.add(["app.py"])
    repository.index.commit("initial")
    return repository


def test_empty_local_target_routes_to_build(tmp_path):
    target = tmp_path / "new-project"

    decision = resolve_task_intent("分析一下整体需求并创建应用", str(target), "main")

    assert decision.workflow == "build"
    assert decision.repository.has_code is False


def test_existing_repository_and_read_only_goal_route_to_analysis(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)

    decision = resolve_task_intent("分析当前鉴权逻辑，不要修改代码", str(repository), "main")

    assert decision.workflow == "analyze"
    assert decision.repository.code_files == 1
    assert decision.repository.current_branch == "main"


def test_existing_repository_and_improvement_goal_route_to_optimize(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)

    decision = resolve_task_intent("优化启动性能并修复缓存问题", str(repository), "main")

    assert decision.workflow == "optimize"


def test_optimization_allows_dirty_repository_for_isolated_snapshot(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)
    (repository / "notes.txt").write_text("not committed\n", encoding="utf-8")
    decision = resolve_task_intent("优化启动性能", str(repository), "main")

    require_clean_build_worktree(decision)


def test_read_only_analysis_allows_dirty_repository(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)
    (repository / "notes.txt").write_text("not committed\n", encoding="utf-8")
    decision = resolve_task_intent("分析当前代码，不要修改", str(repository), "main")

    require_clean_build_worktree(decision)


def test_existing_repository_and_feature_goal_route_to_build(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)

    decision = resolve_task_intent("新增一个用户登录接口", str(repository), "main")

    assert decision.workflow == "build"


def test_build_rejects_a_target_branch_that_is_not_checked_out(tmp_path):
    repository = tmp_path / "existing"
    repo = _repository(repository)
    repo.create_head("feature")
    decision = resolve_task_intent("新增一个用户登录接口", str(repository), "feature")

    with pytest.raises(Problem) as error:
        require_checked_out_branch(decision)
    assert error.value.code == "git_branch_not_checked_out"


def test_remote_repository_can_be_routed_for_read_only_analysis():
    decision = resolve_task_intent(
        "审查支付模块的边界情况",
        "https://example.com/team/repository.git",
        "release/1.0",
    )

    assert decision.workflow == "analyze"
    assert decision.repository.kind == "git_url"
    assert decision.repository.branch == "release/1.0"


def test_selected_subdirectory_resolves_to_repository_root(tmp_path):
    repository = tmp_path / "existing"
    _repository(repository)
    nested = repository / "src" / "feature"
    nested.mkdir(parents=True)

    decision = resolve_task_intent("分析当前代码", str(nested), "main")

    assert decision.repository.source == str(repository)
    assert decision.repository.current_branch == "main"
