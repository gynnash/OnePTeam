import git
import pytest

from onep.greenfield.git_session import GreenfieldGitSession


def test_rejects_dirty_source_repository(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "tracked.txt").write_text("base")
    repo.index.add(["tracked.txt"])
    repo.index.commit("initial")
    (tmp_path / "tracked.txt").write_text("user change")

    with pytest.raises(ValueError, match="dirty"):
        GreenfieldGitSession(tmp_path, "run-1")


def test_runtime_project_context_is_not_a_patch_change(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "README.md").write_text("base")
    repo.index.add(["README.md"])
    repo.index.commit("initial")

    session = GreenfieldGitSession(tmp_path, "run-1")
    session.start()
    session.begin_attempt()
    (tmp_path / "project_context.md").write_text("generated runtime context")
    (tmp_path / "app.py").write_text("VALUE = 1\n")

    assert session.changed_files() == ["app.py"]


def test_sqlite_runtime_sidecars_are_not_patch_changes(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "README.md").write_text("base")
    repo.index.add(["README.md"])
    repo.index.commit("initial")

    session = GreenfieldGitSession(tmp_path, "run-1")
    session.start()
    session.begin_attempt()
    data = tmp_path / "data"
    data.mkdir()
    (data / "items.db").write_bytes(b"db")
    (data / "items.db-wal").write_bytes(b"wal")
    (data / "items.db-shm").write_bytes(b"shm")

    assert session.changed_files() == ["data/items.db"]
