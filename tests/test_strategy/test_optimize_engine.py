from pathlib import Path
from onep.strategy.optimize_engine import OptimizeEngine
from onep.strategy.models import StrategyItem

def test_engine_returns_structure():
    engine = OptimizeEngine()
    item = StrategyItem(
        title="test", file_location="f.py:1",
        summary="test", tags=["perf"], impact="medium",
    )
    result = engine.execute(item, "/tmp/src", "/tmp/ws")
    assert "success" in result
    assert "files_changed" in result
    assert "steps" in result
    assert len(result["steps"]) == 1

def test_engine_single_step_name():
    engine = OptimizeEngine()
    item = StrategyItem(
        title="test", file_location="f.py:1",
        summary="test", tags=["style"], impact="low",
    )
    result = engine.execute(item, "/tmp/src", "/tmp/ws")
    step_names = [s["name"] for s in result["steps"]]
    assert step_names == ["execute"]

def test_engine_no_llm_returns_error():
    engine = OptimizeEngine()
    item = StrategyItem(
        title="test", file_location="f.py:1",
        summary="test", tags=["perf"], impact="high",
    )
    result = engine.execute(item, "/tmp/src", "/tmp/ws", llm_adapter=None)
    assert result["success"] is False
    assert result["error"] == "LLM not available"
