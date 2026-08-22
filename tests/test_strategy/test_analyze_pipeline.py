from onep.strategy.analyze_pipeline import (
    analyze_source,
    candidate_from_item,
)
from onep.strategy.models import StrategyItem


class ScanLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, system_prompt=None, user_prompt=None, stage_name=None):
        self.calls.append(stage_name)
        if stage_name == "analyzer":
            # One scanned file classified as strategy-relevant.
            return '{"file": "app.py", "is_strategy": true, "reason": "core"}\n'
        if stage_name == "strategy_architect":
            return '{"title": "Cache", "summary": "cache issue", "file_location": "app.py:1", "tags": ["cache"], "impact": "medium"}\n'
        return "{}"


def test_analyze_source_scans_and_produces_strategy_items(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n")
    items = analyze_source(source, ScanLLM(), project_name="demo")
    assert len(items) == 1
    assert items[0].id.startswith("si-")
    assert items[0].title == "Cache"


def test_analyze_source_includes_user_goal_in_architect_prompt(tmp_path):
    class CapturingLLM(ScanLLM):
        def __init__(self):
            super().__init__()
            self.architect_prompt = ""

        def invoke(self, system_prompt=None, user_prompt=None, stage_name=None):
            if stage_name == "strategy_architect":
                self.architect_prompt = user_prompt or ""
            return super().invoke(system_prompt, user_prompt, stage_name)

    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n")
    llm = CapturingLLM()

    analyze_source(source, llm, project_name="demo", goal="减少首页请求数量")

    assert "减少首页请求数量" in llm.architect_prompt


def test_analyze_source_returns_empty_without_strategy_files(tmp_path):
    class EmptyLLM(ScanLLM):
        def invoke(self, **kwargs):
            if kwargs.get("stage_name") == "analyzer":
                return '{"file": "app.py", "is_strategy": false, "reason": "no"}\n'
            return "{}"

    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n")
    assert analyze_source(source, EmptyLLM()) == []


def test_candidate_from_item_without_generated():
    item = StrategyItem(
        id="si-1", title="Cache", file_location="app.py:1",
        summary="cache issue", tags=["cache"], impact="medium",
    )
    candidate = candidate_from_item(item, ("pytest -q",))
    assert candidate.id == "si-1"
    assert candidate.test_commands == ("pytest -q",)
    assert candidate.focused_test_commands == ()
    assert str(next(iter(candidate.files))) == "app.py"


def test_candidate_from_item_with_generated():
    from types import SimpleNamespace
    item = StrategyItem(
        id="si-1", title="Cache", file_location="app.py:1",
        summary="cache issue", tags=["cache"], impact="medium",
    )
    generated = SimpleNamespace(
        expected_files=("cache.py",),
        dependencies=("other",),
        test_commands=("pytest -q tests/test_cache.py",),
        risk_flags=("schema",),
    )
    candidate = candidate_from_item(item, ("pytest -q",), generated)
    assert sorted(str(path) for path in candidate.files) == [
        "app.py", "cache.py"]
    assert candidate.dependencies == {"other"}
    assert candidate.risk_flags == {"schema"}
    assert candidate.focused_test_commands == ("pytest -q tests/test_cache.py",)
