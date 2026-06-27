import time
from pathlib import Path
import sqlite3
from onep.memory.schema import init_memory_db, MEMORY_DB_PATH
from onep.memory.manager import MemoryManager
from onep.memory.embeddings import NullEmbedder

def override_db_path(tmp_path):
    import onep.memory.schema as s
    s.MEMORY_DB_PATH = str(tmp_path / "mem.db")

def test_capture_and_search(tmp_path):
    override_db_path(tmp_path)
    init_memory_db()
    mgr = MemoryManager()
    entry = mgr.capture(
        source_id="test-project",
        title="Redis缓存策略",
        content="使用Redis的LRU淘汰策略优化性能",
        importance=5,
    )
    assert entry["id"] is not None
    assert entry["title"] == "Redis缓存策略"

    results = mgr.search("缓存策略")
    assert len(results) > 0
    assert any("Redis" in r["title"] for r in results)

def test_capture_with_tags(tmp_path):
    override_db_path(tmp_path)
    init_memory_db()
    mgr = MemoryManager()
    entry = mgr.capture(
        source_id="test-project",
        title="test",
        content="test",
        tags=["自定义", "标签"],
    )
    assert "自定义" in entry["tags"]

def test_search_by_source(tmp_path):
    override_db_path(tmp_path)
    init_memory_db()
    mgr = MemoryManager()
    mgr.capture("src-A", "A的缓存", "内容A")
    mgr.capture("src-B", "B的缓存", "内容B")
    results = mgr.search("缓存", source_id="src-A")
    assert all(r["source_id"] == "src-A" for r in results)

def test_get_status(tmp_path):
    override_db_path(tmp_path)
    init_memory_db()
    mgr = MemoryManager()
    mgr.capture("test", "test", "test")
    status = mgr.status()
    assert status["total_entries"] >= 1
    assert "db_path" in status

def test_clean_low_score(tmp_path):
    override_db_path(tmp_path)
    init_memory_db()
    mgr = MemoryManager()
    mgr.capture("test", "keep", "content", importance=5)
    # Insert a low-score entry directly
    conn = sqlite3.connect(tmp_path / "mem.db")
    conn.execute(
        "INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("low", "test", "discard", "x", '[]', 0, None, None, 0, 0, 0.05),
    )
    conn.commit()
    conn.close()
    removed = mgr.clean(min_score=0.1)
    assert removed >= 1
    results = mgr.search("keep")
    assert any("keep" in r["title"] for r in results)
