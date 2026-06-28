"""Git isolation for Optimize runs."""
from __future__ import annotations

import re
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path

import git


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not cleaned:
        raise ValueError("branch component is empty")
    return cleaned[:60]


class GitPlanSession:
    def __init__(
        self,
        owner: "GitRunSession",
        branch_name: str,
        worktree: Path,
        base_commit: str,
    ):
        self.owner = owner
        self.branch_name = branch_name
        self.worktree = worktree
        self.base_commit = base_commit
        self.repo = git.Repo(worktree)
        self._baseline_untracked: set[str] = set()
        self._commit_sha: str | None = None
        self.capture_baseline()

    def _untracked(self) -> set[str]:
        output = self.repo.git.ls_files("--others", "--exclude-standard")
        return {line for line in output.splitlines() if line}

    def _new_untracked(self) -> set[str]:
        return self._untracked() - self._baseline_untracked

    def capture_baseline(self) -> None:
        self._baseline_untracked = self._untracked()

    def changed_files(self) -> list[str]:
        tracked = {
            item.a_path or item.b_path
            for item in self.repo.head.commit.diff(None)
            if item.a_path or item.b_path
        }
        return sorted(tracked | self._new_untracked())

    def diff(self) -> str:
        parts = [self.repo.git.diff("--binary", "--no-ext-diff", self.base_commit)]
        for relative in sorted(self._new_untracked()):
            path = self.worktree / relative
            if path.is_file() and not path.is_symlink():
                try:
                    content = path.read_text(errors="replace")
                except OSError:
                    content = "<unreadable>"
                parts.append(f"\n--- /dev/null\n+++ b/{relative}\n{content}")
        return "".join(parts)

    def commit(self, message: str) -> str:
        if self._commit_sha is not None:
            raise RuntimeError("Plan already committed")
        if not self.changed_files():
            raise RuntimeError("Plan has no changes")
        self.repo.git.add("-u")
        new_files = sorted(self._new_untracked())
        if new_files:
            self.repo.index.add(new_files)
        commit = self.repo.index.commit(message)
        self._commit_sha = commit.hexsha
        self.owner._successful_commits[commit.hexsha] = self
        return commit.hexsha

    def rollback(self) -> None:
        self.repo.git.reset("--hard", self.base_commit)
        created = sorted(
            self._new_untracked(),
            key=lambda value: len(Path(value).parts),
            reverse=True,
        )
        root = self.worktree.resolve()
        for relative in created:
            path = self.worktree / relative
            try:
                path.absolute().relative_to(root)
            except ValueError:
                continue
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
        for parent in {
            (self.worktree / relative).parent for relative in created
        }:
            if parent != self.worktree:
                try:
                    parent.rmdir()
                except OSError:
                    pass
        if self.repo.is_dirty():
            raise RuntimeError("rollback_failed: tracked files remain dirty")
        if self._untracked() != self._baseline_untracked:
            raise RuntimeError("rollback_failed: untracked baseline mismatch")

    def remove(self, delete_branch: bool = False) -> None:
        if self.worktree.exists():
            self.owner.source_repo.git.worktree(
                "remove", "--force", str(self.worktree)
            )
        self.owner.source_repo.git.worktree("prune")
        if delete_branch and self.branch_name in self.owner.source_repo.heads:
            self.owner.source_repo.delete_head(self.branch_name, force=True)


class GitRunSession:
    def __init__(self, source: Path, run_dir: Path, run_id: str):
        self.source = Path(source).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.run_id = _slug(run_id)
        self.source_repo = git.Repo(self.source)
        if self.source_repo.bare:
            raise ValueError("source must be a non-bare Git repository")
        if self.source_repo.head.is_detached:
            raise ValueError("source repository must have a named branch")
        if self.source_repo.is_dirty(untracked_files=True):
            dirty = [
                line for line in self.source_repo.git.status(
                    "--porcelain"
                ).splitlines() if line
            ]
            raise ValueError(
                "source repository is dirty: " + ", ".join(dirty)
            )
        self.base_branch = self.source_repo.active_branch.name
        self.base_commit = self.source_repo.head.commit.hexsha
        self.integration_branch = f"onep/optimize-{self.run_id}"
        self.integration_worktree = self.run_dir / "integration"
        self._plans: list[GitPlanSession] = []
        self._successful_commits: dict[str, GitPlanSession] = {}
        self._pre_pick_head: str | None = None
        self._lock = threading.RLock()
        self.last_group_errors: dict[str, str] = {}

    def _unique_branch(self, preferred: str) -> str:
        existing = {head.name for head in self.source_repo.heads}
        if preferred not in existing:
            return preferred
        suffix = 2
        while f"{preferred}-{suffix}" in existing:
            suffix += 1
        return f"{preferred}-{suffix}"

    def create_integration_branch(self) -> str:
        if self.integration_worktree.exists():
            return self.integration_branch
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.integration_branch = self._unique_branch(self.integration_branch)
        self.source_repo.git.worktree(
            "add",
            "-b",
            self.integration_branch,
            str(self.integration_worktree),
            self.base_commit,
        )
        return self.integration_branch

    def create_plan_session(
        self, item_id: str, slug: str
    ) -> GitPlanSession:
        with self._lock:
            if not self.integration_worktree.exists():
                raise RuntimeError("integration branch has not been created")
            base = git.Repo(self.integration_worktree).head.commit.hexsha
            return self._create_plan_at_base(item_id, slug, base)

    def _create_plan_at_base(
        self, item_id: str, slug: str, base: str
    ) -> GitPlanSession:
        preferred = f"onep/plan-{_slug(item_id)}-{_slug(slug)}"
        branch = self._unique_branch(preferred)
        worktree = self.run_dir / "worktrees" / _slug(item_id)
        if worktree.exists():
            worktree = worktree.with_name(f"{worktree.name}-{len(self._plans) + 1}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self.source_repo.git.worktree(
            "add", "-b", branch, str(worktree), base
        )
        plan = GitPlanSession(self, branch, worktree, base)
        self._plans.append(plan)
        return plan

    def create_plan_group(self, candidates) -> dict[str, GitPlanSession]:
        with self._lock:
            if not self.integration_worktree.exists():
                raise RuntimeError("integration branch has not been created")
            base = git.Repo(self.integration_worktree).head.commit.hexsha
            sessions = {}
            self.last_group_errors = {}
            for candidate in candidates:
                try:
                    sessions[candidate.id] = self._create_plan_at_base(
                        candidate.id, candidate.title, base
                    )
                except Exception as exc:
                    self.last_group_errors[candidate.id] = str(exc)
            return sessions

    def integrate(self, commit_sha: str) -> str:
        with self._lock:
            if commit_sha not in self._successful_commits:
                raise ValueError("commit does not belong to a successful Plan")
            repo = git.Repo(self.integration_worktree)
            self._pre_pick_head = repo.head.commit.hexsha
            try:
                repo.git.cherry_pick(commit_sha)
            except git.GitCommandError:
                raise
            return repo.head.commit.hexsha

    @contextmanager
    def integration_guard(self):
        """Serialize cherry-pick, integration tests, and possible rollback."""
        with self._lock:
            yield

    def abort_cherry_pick(self) -> None:
        with self._lock:
            repo = git.Repo(self.integration_worktree)
            try:
                repo.git.cherry_pick("--abort")
            except git.GitCommandError:
                if self._pre_pick_head:
                    repo.git.reset("--hard", self._pre_pick_head)
            if self._pre_pick_head:
                repo.git.reset("--hard", self._pre_pick_head)

    def cleanup(self) -> None:
        for plan in list(self._plans):
            plan.remove(delete_branch=False)
        if self.integration_worktree.exists():
            self.source_repo.git.worktree(
                "remove", "--force", str(self.integration_worktree)
            )
        self.source_repo.git.worktree("prune")
