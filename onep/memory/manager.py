"""MemoryManager — unified interface for ingest, search, and maintenance."""
from __future__ import annotations

import json
import time
import uuid
import sqlite3
from typing import Any

from onep.memory.schema import init_memory_db
from onep.memory.search import hybrid_search
from onep.memory.embeddings import get_embedding, floats_to_blob


def _default_db_path() -> str:
    """Resolve the default DB path at call time so tests can monkeypatch
    onep.memory.schema.MEMORY_DB_PATH before creating a MemoryManager."""
    import onep.memory.schema as _schema

    return _schema.MEMORY_DB_PATH


class MemoryManager:
    """Central memory operations: capture, search, status, clean."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = _default_db_path()
        self.db_path = db_path
        init_memory_db(db_path)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def capture(
        self,
        source_id: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 0,
        model: str = "null",
    ) -> dict[str, Any]:
        """Ingest a new memory entry. Returns the stored row as dict."""
        now = int(time.time())
        entry_id = uuid.uuid4().hex[:12]

        if tags is None:
            tags = []

        embedding_vec = get_embedding(title + "\n" + content, model=model)
        embedding_blob = floats_to_blob(embedding_vec)

        tags_json = json.dumps(tags, ensure_ascii=False)

        self.conn.execute(
            "INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id, source_id, title, content, tags_json,
                importance, embedding_blob, model, now, now, 1.0,
            ),
        )
        self.conn.commit()

        # Update FTS — use integer SQLite rowid, not text id
        try:
            rowid = self.conn.execute(
                "SELECT rowid FROM memory_entries WHERE id=?", (entry_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO memory_fts(rowid, title, content, tags) VALUES (?,?,?,?)",
                (rowid, title, content, tags_json),
            )
        except (sqlite3.OperationalError, TypeError):
            pass
        self.conn.commit()

        return self._row_to_dict(
            self.conn.execute(
                "SELECT * FROM memory_entries WHERE id=?", (entry_id,)
            ).fetchone()
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        source_id: str | None = None,
        min_score: float = -1.0,
    ) -> list[dict[str, Any]]:
        """Search memories. Optionally filter by source_id."""
        results = hybrid_search(self.conn, query, top_k=top_k)
        if source_id:
            results = [r for r in results if r.get("source_id") == source_id]
        results = [r for r in results if r.get("score", 0) >= min_score]
        return results[:top_k]

    def status(self) -> dict[str, Any]:
        """Return memory system statistics."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM memory_entries"
        ).fetchone()[0]
        sources = self.conn.execute(
            "SELECT source_id, COUNT(*) as cnt FROM memory_entries "
            "GROUP BY source_id ORDER BY cnt DESC"
        ).fetchall()
        return {
            "db_path": self.db_path,
            "total_entries": total,
            "sources": [{"source_id": s[0], "count": s[1]} for s in sources],
        }

    def clean(self, min_score: float = 0.1) -> int:
        """Remove entries with decay_factor below threshold and importance=0.
        Returns number of removed entries."""
        cursor = self.conn.execute(
            "DELETE FROM memory_entries WHERE decay_factor < ? AND importance = 0",
            (min_score,),
        )
        self.conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_dict(row: tuple | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cols = ["id", "source_id", "title", "content", "tags", "importance",
                "embedding", "embedding_model", "created_at", "updated_at",
                "decay_factor"]
        return dict(zip(cols, row))
