from onep.runtime.environment import LocalWorktreeEnvironment


def test_environment_confines_paths_and_runs_commands(tmp_path):
    environment = LocalWorktreeEnvironment(tmp_path)
    environment.write_text("src/app.py", "value = 1\n")
    assert environment.read_text("src/app.py") == "value = 1\n"
    result = environment.run("printf ok", timeout=2)
    assert result.exit_code == 0
    assert result.stdout == "ok"


def test_environment_rejects_sibling_prefix_escape(tmp_path):
    environment = LocalWorktreeEnvironment(tmp_path / "work")
    try:
        environment.resolve("../workspace-escape/file.py")
    except ValueError as exc:
        assert "outside workspace" in str(exc)
    else:
        raise AssertionError("path escape was accepted")
