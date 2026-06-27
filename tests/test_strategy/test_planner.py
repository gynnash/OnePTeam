from pathlib import Path

from onep.strategy.models import StrategyItem
from onep.strategy.planner import (
    _build_standard_prompt, _build_full_prompt,
    generate_standard_plan, generate_full_plan,
    STANDARD_PLAN_TEMPLATE, FULL_PLAN_APPENDIX,
)


def test_standard_prompt_includes_item_fields():
    item = StrategyItem(title="缓存优化", file_location="cache.py:30", summary="全量刷新问题", tags=["缓存策略"], impact="high")
    prompt = _build_standard_prompt(item)
    assert "缓存优化" in prompt and "cache.py:30" in prompt and "全量刷新问题" in prompt


def test_full_prompt_includes_standard_plan():
    prompt = _build_full_prompt(StrategyItem(title="t", file_location="f:1"), "# Plan: test\n\n问题描述内容...")
    assert "问题描述内容" in prompt and "伪代码" in prompt


def test_standard_plan_template_has_all_sections():
    content = STANDARD_PLAN_TEMPLATE.format(title="T", file_location="f:1", tags="t1", impact="high",
        timestamp="2026-01-01", problem_description="p", optimization_direction="o",
        implementation_approach="i", risk_assessment="r", reference_solutions="ref")
    for section in ["基本信息", "问题描述", "优化方向", "实现思路", "风险评估", "参考方案"]:
        assert f"## {section}" in content


def test_full_plan_appendix_has_all_sections():
    content = FULL_PLAN_APPENDIX.format(pseudocode="p", data_comparison="d", priority_and_dependencies="prio")
    for section in ["伪代码 / 架构变更", "数据对比", "优先级与依赖"]:
        assert f"## {section}" in content


def test_generate_standard_plan_no_llm(tmp_path: Path):
    ws = tmp_path
    (ws / ".onep").mkdir(parents=True, exist_ok=True)
    assert generate_standard_plan(StrategyItem(title="Test", file_location="f:1"), ws, llm_adapter=None) is None


def test_generate_full_plan_no_llm(tmp_path: Path):
    ws = tmp_path
    (ws / ".onep").mkdir(parents=True, exist_ok=True)
    assert generate_full_plan(StrategyItem(title="Test", file_location="f:1"), "# s", ws, llm_adapter=None) is None


class CapturingLLM:
    def __init__(self):
        self.user_prompt = ""

    def invoke(self, **kwargs):
        self.user_prompt = kwargs["user_prompt"]
        return "# Generated plan"


def test_standard_plan_prompt_contains_memory(tmp_path):
    llm = CapturingLLM()
    generate_standard_plan(
        StrategyItem(title="Test", file_location="f:1"),
        tmp_path,
        llm_adapter=llm,
        memory_context="<relevant_memories>past plan</relevant_memories>",
    )

    assert "<relevant_memories>" in llm.user_prompt


def test_full_plan_prompt_contains_memory(tmp_path):
    item = StrategyItem(title="Test", file_location="f:1")
    llm = CapturingLLM()
    generate_full_plan(
        item,
        "# Standard",
        tmp_path,
        llm_adapter=llm,
        memory_context="<relevant_memories>past plan</relevant_memories>",
    )

    assert "<relevant_memories>" in llm.user_prompt
