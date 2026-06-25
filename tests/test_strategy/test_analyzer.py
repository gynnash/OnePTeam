from onep.strategy.analyzer import parse_analysis_response


def test_parse_analysis_response():
    response = '''{"title": "缓存优化", "file_location": "cache.py:30", "tags": ["缓存"], "impact": "high", "summary": "全量刷新"}
{"title": "日志策略", "file_location": "log.py:10", "tags": ["可观测性"], "impact": "low", "summary": "级别不统一"}'''
    items = parse_analysis_response(response)
    assert len(items) == 2
    assert items[0].title == "缓存优化"
    assert items[0].impact == "high"
    assert items[1].impact == "low"


def test_parse_analysis_response_skips_invalid_lines():
    response = '''{"title": "ok", "file_location": "f.py:1", "tags": [], "impact": "low", "summary": "x"}
invalid json here
{"title": "also ok", "file_location": "g.py:2", "tags": [], "impact": "medium", "summary": "y"}'''
    items = parse_analysis_response(response)
    assert len(items) == 2


def test_parse_analysis_response_empty():
    assert parse_analysis_response("") == []
    assert parse_analysis_response("not json at all") == []


def test_parse_analysis_response_sorts_by_impact():
    response = '''{"title": "low", "file_location": "a:1", "tags": [], "impact": "low", "summary": "x"}
{"title": "high", "file_location": "b:1", "tags": [], "impact": "high", "summary": "x"}
{"title": "medium", "file_location": "c:1", "tags": [], "impact": "medium", "summary": "x"}'''
    items = parse_analysis_response(response)
    assert items[0].impact == "high"
    assert items[1].impact == "medium"
    assert items[2].impact == "low"
