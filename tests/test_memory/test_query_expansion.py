import pytest
from onep.memory.query_expansion import expand_query

def test_expand_query_no_llm_returns_original():
    expanded = expand_query("缓存策略", llm_adapter=None)
    assert "缓存策略" in expanded

def test_expand_query_caches_result(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r1 = expand_query("LLM路由")
    r2 = expand_query("LLM路由")
    assert r1 == r2

def test_short_query_returns_single():
    result = expand_query("ab", llm_adapter=None)
    assert result == ["ab"]
