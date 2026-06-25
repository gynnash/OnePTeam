from pathlib import Path
from onep.strategy.analyzer import (
    _build_analysis_prompt, _parse_analysis_response, analyze_strategies,
)


def test_build_analysis_prompt_includes_files():
    prompt = _build_analysis_prompt(["src/ranker.py", "src/cache.py"], Path("/project"))
    assert "src/ranker.py" in prompt
    assert "src/cache.py" in prompt
    assert "/project" in prompt


def test_parse_analysis_response():
    response = '''{"title": "缓存优化", "file_location": "cache.py:30", "tags": ["缓存"], "impact": "high", "summary": "全量刷新"}
{"title": "日志策略", "file_location": "log.py:10", "tags": ["可观测性"], "impact": "low", "summary": "级别不统一"}'''
    items = _parse_analysis_response(response)
    assert len(items) == 2
    assert items[0].title == "缓存优化"
    assert items[0].impact == "high"


def test_parse_analysis_response_skips_invalid_lines():
    response = '''{"title": "ok", "file_location": "f.py:1", "tags": [], "impact": "low", "summary": "x"}
invalid json here
{"title": "also ok", "file_location": "g.py:2", "tags": [], "impact": "medium", "summary": "y"}'''
    assert len(_parse_analysis_response(response)) == 2


def test_analyze_strategies_empty_input():
    assert analyze_strategies([], Path(".")) == []


def test_analyze_strategies_no_llm():
    items = analyze_strategies(["test.py"], Path("."), llm_adapter=None)
    assert len(items) == 1
    assert items[0].title == "LLM不可用，策略分析待执行"
