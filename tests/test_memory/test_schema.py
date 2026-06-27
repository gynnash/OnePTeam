import sqlite3
from pathlib import Path
from onep.memory.schema import init_memory_db, get_connection

def test_init_creates_tables(tmp_path):
    db_path = str(tmp_path / "memory.db")
    init_memory_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in tables}
    assert "memory_entries" in names
    assert "memory_fts" in names

def test_init_is_idempotent(tmp_path):
    db_path = str(tmp_path / "memory.db")
    init_memory_db(db_path)
    init_memory_db(db_path)  # should not raise

def test_get_connection_returns_singleton(tmp_path, monkeypatch):
    db_path = str(tmp_path / "memory.db")
    monkeypatch.setattr("onep.memory.schema.MEMORY_DB_PATH", db_path)
    init_memory_db(db_path)
    c1 = get_connection(db_path)
    c2 = get_connection(db_path)
    assert c1 is c2

def test_schema_migration_adds_columns(tmp_path):
    # Simulate old schema — create table without a newer column
    db_path = str(tmp_path / "memory.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE memory_entries (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    # init should add missing columns without error
    init_memory_db(db_path)
    cols = {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(memory_entries)")}
    assert "decay_factor" in cols
