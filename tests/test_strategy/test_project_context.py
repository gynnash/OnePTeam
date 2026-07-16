from onep.strategy.project_context import build_project_context


def test_build_project_context_uses_repository_facts_and_manual_context(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (source / "app.py").write_text("value = 1\n")
    (source / "AGENTS.md").write_text("Run focused tests before the full suite.\n")
    workspace = tmp_path / "workspace"
    context = build_project_context(str(source), workspace)
    assert "Python files: 1" in context
    assert "Has pyproject.toml" in context
    assert "Run focused tests" in context
    assert (workspace / "project_context.md").read_text() == context
