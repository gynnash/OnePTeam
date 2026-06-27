"""SQLite schema for memory system."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

MEMORY_DB_PATH = str(Path.home() / ".onep" / "memory" / "memory.db")


def _ensure_dir(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def init_memory_db(db_path: str | None = None) -> None:
    """Initialize the memory database, creating tables if absent."""
    db_path = db_path or MEMORY_DB_PATH
    _ensure_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_entries (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            importance INTEGER NOT NULL DEFAULT 0,
            embedding BLOB,
            embedding_model TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            decay_factor REAL NOT NULL DEFAULT 1.0
        )
    """)
    # Ensure any columns added in newer versions exist, before creating indexes
    _migrate_add_columns(conn)
    # Index creation wrapped in try/except so an unexpectedly incomplete table
    # (e.g. from test fixtures or early schema evolution) does not block startup.
    for index_sql in [
        "CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_entries(source_id)",
        "CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_entries(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_memory_tags ON memory_entries(tags)",
    ]:
        try:
            conn.execute(index_sql)
        except sqlite3.OperationalError:
            pass
    # FTS5 may fail if SQLite compiled without it — not fatal
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                title, content, tags,
                content='memory_entries',
                content_rowid='rowid'
            )
        """)
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _migrate_add_columns(conn: sqlite3.Connection) -> None:
    """Add columns that may not exist in older schema versions."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(memory_entries)")}
    for col, col_def in [
        ("tags", "TEXT NOT NULL DEFAULT '[]'"),
        ("importance", "INTEGER NOT NULL DEFAULT 0"),
        ("embedding", "BLOB"),
        ("embedding_model", "TEXT"),
        ("decay_factor", "REAL NOT NULL DEFAULT 1.0"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE memory_entries ADD COLUMN {col} {col_def}")


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Get a singleton SQLite connection. Thread-safe."""
    global _conn
    db_path = db_path or MEMORY_DB_PATH
    with _lock:
        if _conn is None:
            _ensure_dir(db_path)
            _conn = sqlite3.connect(db_path, check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
        return _conn
