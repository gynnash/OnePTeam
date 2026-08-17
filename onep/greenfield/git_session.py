"""In-place Git safety for Greenfield runs."""

from __future__ import annotations

from pathlib import Path
import re

import git


class GreenfieldGitSession:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        recoverable_wip: Path | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.repo = git.Repo(self.workspace)
        if self.repo.bare:
            raise ValueError("repository is bare; use a repository with a working tree")
        if self.repo.head.is_detached:
            raise ValueError("repository is on detached HEAD; switch to a named branch")
        self._exclude_runtime()
        if recoverable_wip is not None:
            self._clean_recoverable_wip(Path(recoverable_wip))
        dirty = self._user_changes()
        if dirty:
            raise ValueError(
                "working tree is dirty; commit or stash these files first: "
                + ", ".join(dirty)
            )
        self.base_branch = self.repo.active_branch.name
        self.base_commit = self.repo.head.commit.hexsha
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip(".-")
        self.run_branch = self._unique_branch(f"onep/greenfield-{slug}")
        self._attempt_commit = self.base_commit
        self._attempt_untracked: set[str] = set()
        self._attempt_active = False

    def _clean_recoverable_wip(self, root: Path) -> None:
        """Remove an exactly backed-up WIP snapshot left by an interrupted process.

        The recorder restores the same snapshot after ``begin_attempt``.  Cleaning it
        here is important: otherwise Git safety rejects OneP's own files, or the
        attempt baseline incorrectly treats pre-existing untracked WIP as user work.
        Files are touched only when their bytes exactly match the saved snapshot.
        """
        manifest = root / "manifest.json"
        try:
            import json

            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            return
        tracked = set(self.repo.git.ls_files().splitlines())
        workspace = self.workspace
        for relative in data.get("files") or []:
            relative = str(relative)
            backup = root / "files" / relative
            target = workspace / relative
            try:
                target.resolve().relative_to(workspace)
            except (OSError, ValueError):
                continue
            if (
                not backup.is_file()
                or not target.is_file()
                or target.is_symlink()
                or target.read_bytes() != backup.read_bytes()
            ):
                continue
            if relative in tracked:
                self.repo.git.checkout("--", relative)
            else:
                target.unlink()
        for relative in data.get("deleted") or []:
            relative = str(relative)
            target = workspace / relative
            try:
                target.resolve().relative_to(workspace)
            except (OSError, ValueError):
                continue
            if relative in tracked and not target.exists():
                self.repo.git.checkout("--", relative)

    def _user_changes(self) -> list[str]:
        return [
            line
            for line in self.repo.git.status("--porcelain").splitlines()
            if line and ".onep/" not in line[3:]
        ]

    def _exclude_runtime(self) -> None:
        exclude = Path(self.repo.git_dir) / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        content = exclude.read_text() if exclude.exists() else ""
        patterns = (
            ".onep/",
            "project_context.md",
            "__pycache__/",
            ".pytest_cache/",
            "node_modules/",
            ".coverage",
            "coverage/",
            "htmlcov/",
            "output/",
            "outputs/",
            "logs/",
            "*.log",
            "*.db-wal",
            "*.db-shm",
            "*.db-journal",
            "*.db",
            "*.egg-info/",
            "*.dist-info/",
            "build/",
            "dist/",
        )
        lines = set(content.splitlines())
        missing = [pattern for pattern in patterns if pattern not in lines]
        if missing:
            separator = "" if not content or content.endswith("\n") else "\n"
            exclude.write_text(
                content + separator + "".join(f"{pattern}\n" for pattern in missing)
            )

    def _unique_branch(self, preferred: str) -> str:
        names = {head.name for head in self.repo.heads}
        if preferred not in names:
            return preferred
        index = 2
        while f"{preferred}-{index}" in names:
            index += 1
        return f"{preferred}-{index}"

    def start(self) -> None:
        if self.repo.active_branch.name == self.run_branch:
            return
        if self.run_branch in {head.name for head in self.repo.heads}:
            self.repo.git.checkout(self.run_branch)
        else:
            self.repo.git.checkout("-b", self.run_branch)

    def resume(self, branch: str) -> None:
        if branch not in {head.name for head in self.repo.heads}:
            raise ValueError(f"Greenfield run branch not found: {branch}")
        if self.repo.active_branch.name != branch:
            dirty = self._user_changes()
            if dirty:
                raise ValueError(
                    "cannot resume with a dirty working tree: " + ", ".join(dirty)
                )
            self.repo.git.checkout(branch)
        self.run_branch = branch

    def begin_attempt(self) -> None:
        self._attempt_commit = self.repo.head.commit.hexsha
        self._attempt_untracked = self._untracked()
        self._attempt_active = True

    def changed_files(self) -> list[str]:
        tracked = {
            item.a_path or item.b_path
            for item in self.repo.head.commit.diff(None)
            if item.a_path or item.b_path
        }
        return sorted(tracked | (self._untracked() - self._attempt_untracked))

    def diff(self) -> str:
        parts = [self.repo.git.diff("--binary", "--no-ext-diff", self._attempt_commit)]
        for relative in sorted(self._untracked() - self._attempt_untracked):
            path = self.workspace / relative
            if path.is_file() and not path.is_symlink():
                parts.append(
                    f"\n--- /dev/null\n+++ b/{relative}\n"
                    + path.read_text(errors="replace")
                )
        return "".join(parts)

    def commit(self, message: str) -> str:
        changed = self.changed_files()
        if not changed:
            raise RuntimeError("Engineer produced no code changes")
        self.repo.git.add("-A")
        commit = self.repo.index.commit(message)
        self._attempt_active = False
        return commit.hexsha

    def rollback_attempt(self) -> None:
        if not self._attempt_active:
            return
        self.repo.git.reset("--hard", self._attempt_commit)
        root = self.workspace.resolve()
        for relative in sorted(
            self._untracked() - self._attempt_untracked,
            key=lambda value: len(Path(value).parts),
            reverse=True,
        ):
            target = self.workspace / relative
            try:
                target.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if target.is_file() or target.is_symlink():
                target.unlink(missing_ok=True)
            elif target.is_dir():
                import shutil

                shutil.rmtree(target)
        self._attempt_active = False

    def _untracked(self) -> set[str]:
        output = self.repo.git.ls_files("--others", "--exclude-standard")
        return {line for line in output.splitlines() if line}
