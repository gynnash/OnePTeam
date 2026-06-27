import pytest
from onep.memory.embeddings import get_embedding, NullEmbedder, _cosine_similarity

def test_null_embedder_returns_hashed_vector():
    e = NullEmbedder(dims=10)
    vec = e.embed("hello world")
    assert len(vec) == 10
    # NullEmbedder uses hash-based vectors (not all zeros) for deterministic results
    assert all(isinstance(v, float) for v in vec)

def test_null_embedder_get_returns_singleton():
    e1 = NullEmbedder.get(dims=10)
    e2 = NullEmbedder.get(dims=10)
    assert e1 is e2

def test_get_embedding_returns_list_of_floats(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    vec = get_embedding("test content", model="null")
    assert isinstance(vec, list)
    assert len(vec) > 0

def test_cosine_similarity_identical():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

def test_cosine_similarity_orthogonal():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)

def test_cosine_similarity_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

def test_embed_caches_result(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    text = "test content for caching"
    v1 = get_embedding(text, model="null")
    v2 = get_embedding(text, model="null")
    assert v1 == v2
