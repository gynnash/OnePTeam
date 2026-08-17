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


def test_cleans_exact_interrupted_wip_before_git_safety(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "tracked.txt").write_text("base")
    repo.index.add(["tracked.txt"])
    repo.index.commit("initial")

    (tmp_path / "tracked.txt").write_text("wip tracked")
    (tmp_path / "new.py").write_text("WIP = True\n")
    wip = tmp_path / ".onep/greenfield/runs/run/slices/S1/wip"
    (wip / "files").mkdir(parents=True)
    (wip / "files/tracked.txt").write_text("wip tracked")
    (wip / "files/new.py").write_text("WIP = True\n")
    (wip / "manifest.json").write_text(
        '{"plan_id":"S1","files":["tracked.txt","new.py"]}'
    )

    session = GreenfieldGitSession(tmp_path, "run-1", recoverable_wip=wip)

    assert session._user_changes() == []
    assert (tmp_path / "tracked.txt").read_text() == "base"
    assert not (tmp_path / "new.py").exists()


def test_cleans_recoverable_wip_deletion_before_git_safety(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "obsolete.py").write_text("old\n")
    repo.index.add(["obsolete.py"])
    repo.index.commit("initial")
    (tmp_path / "obsolete.py").unlink()
    wip = tmp_path / ".onep/greenfield/runs/run/slices/S1/wip"
    wip.mkdir(parents=True)
    (wip / "manifest.json").write_text(
        '{"plan_id":"S1","files":[],"deleted":["obsolete.py"]}'
    )

    session = GreenfieldGitSession(tmp_path, "run-1", recoverable_wip=wip)

    assert session._user_changes() == []
    assert (tmp_path / "obsolete.py").read_text() == "old\n"


def test_does_not_clean_user_file_that_differs_from_saved_wip(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "tracked.txt").write_text("base")
    repo.index.add(["tracked.txt"])
    repo.index.commit("initial")
    (tmp_path / "new.py").write_text("USER = True\n")
    wip = tmp_path / ".onep/greenfield/runs/run/slices/S1/wip"
    (wip / "files").mkdir(parents=True)
    (wip / "files/new.py").write_text("WIP = True\n")
    (wip / "manifest.json").write_text('{"plan_id":"S1","files":["new.py"]}')

    with pytest.raises(ValueError, match="dirty"):
        GreenfieldGitSession(tmp_path, "run-1", recoverable_wip=wip)

    assert (tmp_path / "new.py").read_text() == "USER = True\n"


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


def test_sqlite_runtime_files_are_not_patch_changes(tmp_path):
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

    assert session.changed_files() == []


def test_log_and_output_runtime_files_are_not_patch_changes(tmp_path):
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
    (tmp_path / "output").mkdir()
    (tmp_path / "output/weekly_scan.log").write_text("runtime\n")
    (tmp_path / "debug.log").write_text("runtime\n")

    assert session.changed_files() == []


def test_python_package_metadata_is_not_a_patch_change(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (tmp_path / "README.md").write_text("base")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    session = GreenfieldGitSession(tmp_path, "run")
    session.start()
    session.begin_attempt()
    metadata = tmp_path / "src/demo.egg-info"
    metadata.mkdir(parents=True)
    (metadata / "PKG-INFO").write_text("generated\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")

    assert session.changed_files() == ["app.py"]
