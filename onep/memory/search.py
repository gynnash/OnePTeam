"""Hybrid search: vector cosine + FTS5 BM25 + MMR dedup + temporal decay."""
from __future__ import annotations

import math
import sqlite3
import time
from typing import Any

from onep.memory.embeddings import NullEmbedder


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    alpha: float = 0.7,
) -> list[dict[str, Any]]:
    """Run hybrid search returning top_k results after MMR + decay."""
    all_rows = _fetch_all_entries(conn)
    if not all_rows:
        return []

    query_vec = NullEmbedder.get().embed(query)
    now = int(time.time())

    # --- vector scores ---
    vec_scores: dict[str, float] = {}
    for row in all_rows:
        if row["embedding"]:
            emb = bytes(row["embedding"])
            from onep.memory.embeddings import blob_to_floats, _cosine_similarity

            emb_vec = blob_to_floats(emb)
            vec_scores[row["id"]] = _cosine_similarity(query_vec, emb_vec)
        else:
            vec_scores[row["id"]] = 0.0

    # --- keyword scores (BM25 approximation via FTS5) ---
    kw_scores: dict[str, float] = {}
    try:
        rows = conn.execute(
            "SELECT rowid, rank FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank",
            (query,),
        ).fetchall()
        if rows:
            max_rank = max(abs(r[1]) for r in rows) or 1
            for rowid, rank in rows:
                kw_scores[str(rowid)] = 1.0 / (1.0 + abs(rank) / max_rank)
    except sqlite3.OperationalError:
        pass
    if not kw_scores:
        # Fall back to substring matching
        for row in all_rows:
            score = 0.0
            content_lower = (
                row["title"] + " " + row["content"] + " " + row["tags"]
            ).lower()
            for term in query.lower().split():
                if term in content_lower:
                    score += 0.5
            if score > 0:
                kw_scores[row["id"]] = min(score, 1.0)

    # --- hybrid merge ---
    scores: dict[str, float] = {}
    for row in all_rows:
        v = vec_scores.get(row["id"], 0)
        k = kw_scores.get(row["id"], 0)
        scores[row["id"]] = alpha * v + (1 - alpha) * k

    # --- temporal decay ---
    for row in all_rows:
        row["decay_factor"] = _compute_decay(row["created_at"], now)
        scores[row["id"]] *= row["decay_factor"]
        imp = row.get("importance", 0) or 0
        scores[row["id"]] *= 1.0 + imp * 0.1

    # --- sort by score ---
    scored = [(row, scores.get(row["id"], 0)) for row in all_rows]
    scored.sort(key=lambda x: x[1], reverse=True)

    # --- MMR rerank ---
    selected = _mmr_rerank(scored, top_k)

    return [dict(r, score=s) for r, s in selected]


def _fetch_all_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, source_id, title, content, tags, importance, "
        "embedding, embedding_model, created_at, updated_at, decay_factor "
        "FROM memory_entries"
    ).fetchall()
    cols = [
        "id",
        "source_id",
        "title",
        "content",
        "tags",
        "importance",
        "embedding",
        "embedding_model",
        "created_at",
        "updated_at",
        "decay_factor",
    ]
    return [dict(zip(cols, r)) for r in rows]


def _compute_decay(created_at: int, now: int, lambda_: float = 0.02) -> float:
    """Compute temporal decay factor. lambda_=0.02 means ~35 day half-life."""
    days = (now - created_at) / 86400.0
    return math.exp(-lambda_ * days)


def _mmr_rerank(
    scored: list[tuple[dict, float]], top_k: int, lambda_mmr: float = 0.7
) -> list[tuple[dict, float]]:
    """Max Marginal Relevance reranking."""
    if not scored:
        return []
    if len(scored) <= top_k:
        return scored[:top_k]
    selected: list[tuple[dict, float]] = [scored[0]]
    remaining = scored[1:]

    while len(selected) < top_k and remaining:
        best = None
        best_score = -float("inf")
        for idx, (row, score) in enumerate(remaining):
            relevance = score
            redundancy = max(
                (_text_similarity(row, s_row) for s_row, _ in selected),
                default=0,
            )
            mmr = lambda_mmr * relevance - (1 - lambda_mmr) * redundancy
            if mmr > best_score:
                best_score = mmr
                best = idx
        if best is not None:
            selected.append(remaining.pop(best))
        else:
            break
    return selected


def _text_similarity(a: dict, b: dict) -> float:
    """Simple Jaccard-like similarity on title + tags."""
    a_words = set(
        (a.get("title", "") + " " + a.get("tags", "")).lower().split()
    )
    b_words = set(
        (b.get("title", "") + " " + b.get("tags", "")).lower().split()
    )
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)
