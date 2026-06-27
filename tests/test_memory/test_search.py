import sqlite3
import pytest
from pathlib import Path
from onep.memory.schema import init_memory_db
from onep.memory.search import (
    hybrid_search,
    _compute_decay,
    _mmr_rerank,
    _text_similarity,
)


def make_db(tmp_path):
    db_path = str(tmp_path / "test_search.db")
    init_memory_db(db_path)
    conn = sqlite3.connect(db_path)
    now = int(__import__("time").time())
    rows = [
        (
            "1",
            "proj",
            "缓存策略",
            "使用Redis做缓存层",
            '["缓存","Redis"]',
            5,
            None,
            None,
            now,
            now,
            1.0,
        ),
        (
            "2",
            "proj",
            "LLM路由",
            "多个LLM provider的路由策略",
            '["LLM","路由"]',
            5,
            None,
            None,
            now,
            now,
            1.0,
        ),
        (
            "3",
            "proj",
            "性能优化",
            "数据库查询优化",
            '["性能","数据库"]',
            3,
            None,
            None,
            now - 100 * 86400,
            now - 100 * 86400,
            1.0,
        ),
        (
            "4",
            "proj",
            "缓存策略2",
            "Redis cluster配置",
            '["缓存","Redis"]',
            5,
            None,
            None,
            now,
            now,
            1.0,
        ),
    ]
    conn.executemany(
        "INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    try:
        conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
    except Exception:
        pass
    return conn, now


def test_hybrid_search_returns_results(tmp_path):
    conn, now = make_db(tmp_path)
    results = hybrid_search(conn, "缓存策略", top_k=5)
    assert len(results) > 0
    titles = [r["title"] for r in results]
    assert "缓存策略" in titles or "缓存策略2" in titles


def test_temporal_decay_reduces_old_scores(tmp_path):
    conn, now = make_db(tmp_path)
    results = hybrid_search(conn, "性能优化", top_k=10)
    for r in results:
        if r["id"] == "3":
            assert r["decay_factor"] < 0.5

    persisted = conn.execute(
        "SELECT decay_factor FROM memory_entries WHERE id='3'"
    ).fetchone()[0]
    assert persisted < 0.5


def test_compute_decay():
    now = 1000000
    recent = now - 7 * 86400
    old = now - 90 * 86400
    assert _compute_decay(recent, now) > _compute_decay(old, now)
    assert _compute_decay(now, now) == pytest.approx(1.0)


def test_mmr_rerank_empty():
    result = _mmr_rerank([], top_k=5)
    assert result == []


def test_text_similarity_identical():
    assert _text_similarity(
        {"title": "缓存策略", "tags": '["cache"]'},
        {"title": "缓存策略", "tags": '["cache"]'},
    ) == pytest.approx(1.0)


def test_text_similarity_different():
    sim = _text_similarity(
        {"title": "缓存策略", "tags": '["cache"]'},
        {"title": "LLM路由", "tags": '["llm"]'},
    )
    assert sim < 0.5
