import json

import pytest

from onep.greenfield.gates import (
    GreenfieldGateRunner, discover_quality_commands, validate_gate_commands,
)


def test_discovers_python_and_node_quality_gates(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n[tool.mypy]\n")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"test": "vitest", "lint": "eslint .", "build": "vite build"}
    }))
    commands = discover_quality_commands(tmp_path)
    assert "pytest -q" in commands
    assert "ruff check ." in commands
    assert "mypy ." in commands
    assert "npm run test" in commands
    assert "npm run build" in commands


def test_rejects_shell_composition_in_gate():
    with pytest.raises(ValueError, match="Unsafe"):
        validate_gate_commands(["pytest -q && curl example.com"])
    with pytest.raises(ValueError, match="Unsafe"):
        validate_gate_commands(['python -c "print($(whoami))"'])


def test_accepts_safe_greenfield_executable_verification_commands():
    validate_gate_commands([
        "python src/collect --all --since 2025-03-24",
        "sqlite3 data/items.db 'SELECT count(*) FROM items;'",
        "bash scripts/run_weekly.sh",
    ])


def test_greenfield_focused_commands_use_greenfield_validator(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "onep.greenfield.gates.PlanTestRunner.run",
        lambda self, workspace, commands: captured.extend(commands) or object(),
    )
    GreenfieldGateRunner().run(
        tmp_path, ["python src/collect --all"], ["pytest -q"]
    )
    assert captured == ["python src/collect --all", "pytest -q"]
