from click.testing import CliRunner
from onep.cli.memory_cmd import memory_group

def test_memory_status(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.memory.schema.MEMORY_DB_PATH", str(tmp_path / "mem.db")
    )
    from onep.memory.schema import init_memory_db
    init_memory_db()
    runner = CliRunner()
    result = runner.invoke(memory_group, ["status"])
    assert result.exit_code == 0
    assert "0" in result.output  # 0 entries initially

def test_memory_search_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.memory.schema.MEMORY_DB_PATH", str(tmp_path / "mem.db")
    )
    from onep.memory.schema import init_memory_db
    init_memory_db()
    runner = CliRunner()
    result = runner.invoke(memory_group, ["search", "nonexistent"])
    assert result.exit_code == 0
