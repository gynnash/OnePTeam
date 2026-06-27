"""Query expansion — synonym/translation variants for better search recall."""
from __future__ import annotations

_cache: dict[str, list[str]] = {}

_EXPANSION_PROMPT = """Extract the key concept words from this query and list their
synonyms, English translations, and related terms. Return only a JSON array of strings.

Query: {query}

Example:
Query: "缓存策略优化"
Output: ["缓存策略", "cache strategy", "缓存淘汰", "cache eviction", "LRU缓存", "Redis缓存"]"""


def expand_query(query: str, llm_adapter=None) -> list[str]:
    """Expand a query into variant terms. Returns original + variants."""
    if query in _cache:
        return _cache[query]

    if len(query) < 3:
        return [query]

    if llm_adapter is None:
        _cache[query] = [query]
        return [query]

    import json
    try:
        response = llm_adapter.invoke(
            system_prompt="你是一个搜索关键词提取器。",
            user_prompt=_EXPANSION_PROMPT.format(query=query),
            stage_name="query_expansion",
        )
        variants = json.loads(response)
        if isinstance(variants, list):
            all_terms = [query] + [v for v in variants if v != query]
            _cache[query] = all_terms
            return all_terms
    except Exception:
        pass

    _cache[query] = [query]
    return [query]
