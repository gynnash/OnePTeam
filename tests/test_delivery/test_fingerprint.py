import os
from pathlib import Path
import subprocess

from onep.delivery.fingerprint import fingerprint_tree


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "tracked.txt")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def test_fingerprint_tracks_modified_untracked_deleted_and_symlink(tmp_path):
    root = _repository(tmp_path)
    initial = fingerprint_tree(root)
    (root / "tracked.txt").write_text("two", encoding="utf-8")
    modified = fingerprint_tree(root)
    (root / "new.txt").write_text("new", encoding="utf-8")
    untracked = fingerprint_tree(root)
    (root / "tracked.txt").unlink()
    deleted = fingerprint_tree(root)
    os.symlink("new.txt", root / "link.txt")
    linked = fingerprint_tree(root)

    assert (
        len(
            {
                initial.digest,
                modified.digest,
                untracked.digest,
                deleted.digest,
                linked.digest,
            }
        )
        == 5
    )


def test_fingerprint_ignores_gitignored_and_onep_runtime_files(tmp_path):
    root = _repository(tmp_path)
    initial = fingerprint_tree(root)
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")
    (root / ".onep").mkdir()
    (root / ".onep" / "state.json").write_text("runtime", encoding="utf-8")

    assert fingerprint_tree(root).digest == initial.digest
