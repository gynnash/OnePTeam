import json
from pathlib import Path

import pytest

from onep.cli.optimize_cmd import _memory_context
from onep.llm.adapters import TokenUsage
from onep.llm.cost import CostTracker
from onep.strategy.models import StrategyItem
from onep.strategy.planner import generate_optimize_plan
from onep.strategy.scanner import (
    ScanResult,
    aggregate_chunk_results,
    build_content_batches,
)


class JsonLLM:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, **kwargs):
        return self.payload


def test_optimize_planner_returns_validated_metadata(tmp_path):
    payload = json.dumps({
        "plan_markdown": "# Cache Plan",
        "expected_files": ["src/cache.py"],
        "dependencies": ["Foundation"],
        "test_commands": ["pytest tests/test_cache.py -q"],
        "risk_flags": ["semantic_coupling"],
    })
    generated = generate_optimize_plan(
        StrategyItem("Cache", "src/cache.py:1"),
        tmp_path,
        JsonLLM(payload),
        memory_context="<relevant_memories>known</relevant_memories>",
    )
    assert generated.expected_files == ("src/cache.py",)
    assert generated.risk_flags == ("semantic_coupling",)
    assert Path(generated.plan_path).read_text() == "# Cache Plan"


def test_optimize_planner_rejects_unsafe_expected_path(tmp_path):
    payload = json.dumps({
        "plan_markdown": "# Plan",
        "expected_files": ["../outside.py"],
        "dependencies": [],
        "test_commands": ["pytest -q"],
        "risk_flags": [],
    })
    with pytest.raises(ValueError, match="unsafe"):
        generate_optimize_plan(
            StrategyItem("Unsafe", "x.py:1"), tmp_path, JsonLLM(payload)
        )


def test_token_usage_call_ids_are_stable_and_unique(monkeypatch):
    first = TokenUsage(10, 5, 15)
    second = TokenUsage(10, 5, 15)
    assert first.call_id != second.call_id
    monkeypatch.setattr("onep.llm.cost._get_price", lambda *args: 1.0)
    tracker = CostTracker()
    assert tracker.record_usage("a", "m", first).cost is not None
    assert tracker.record_usage("a", "m", first).cost == 0
    assert tracker.record_usage("a", "m", second).cost is not None


def test_multi_chunk_response_without_chunk_ids_falls_back(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("x = 1\n" * 5000)
    entries = [
        entry
        for batch in build_content_batches(tmp_path, [path], max_tokens=300)
        for entry in batch.entries
    ]
    result = aggregate_chunk_results(
        entries, [ScanResult("large.py", False, "legacy")]
    )
    assert result[0].is_strategy
    assert "未返回" in result[0].reason


def test_duplicate_chunk_response_is_explicit_fallback(tmp_path):
    path = tmp_path / "one.py"
    path.write_text("x = 1\n")
    entry = build_content_batches(tmp_path, [path])[0].entries[0]
    duplicate = ScanResult("one.py", False, "no", entry.chunk_id)
    result = aggregate_chunk_results([entry], [duplicate, duplicate])
    assert result[0].is_strategy
    assert "重复" in result[0].reason


def test_optimize_memory_uses_local_loose_global_strict(monkeypatch):
    captured = {}

    def build(self, request):
        captured["request"] = request
        return "memory"

    monkeypatch.setattr(
        "onep.cli.optimize_cmd.MemoryContextBuilder.build", build
    )
    assert _memory_context("code_reviewer", "demo", "review") == "memory"
    request = captured["request"]
    assert request.local_top_k == 6
    assert request.local_min_score == 0.15
    assert request.global_top_k == 3
    assert request.global_min_score == 0.45
