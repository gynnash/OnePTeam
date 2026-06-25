"""Integration tests: verify all strategy components wire together."""
from pathlib import Path

from onep.strategy.models import WorkbenchState, StrategyItem, DialogueTurn
from onep.strategy.persistence import save_workbench, load_workbench, append_dialogue
from onep.strategy.workbench import parse_input


def test_full_data_roundtrip(tmp_path: Path):
    ws = tmp_path
    wb = WorkbenchState(project_name="integration", source_path="./repo")
    wb.items.append(StrategyItem(title="Full roundtrip test", file_location="main.py:42",
                                  summary="Test persistence", impact="high", tags=["测试"]))
    wb.scan_complete = True; wb.analysis_complete = True
    save_workbench(ws, wb)
    loaded = load_workbench(ws)
    assert loaded is not None and loaded.project_name == "integration"
    assert len(loaded.items) == 1 and loaded.items[0].title == "Full roundtrip test"
    assert loaded.items[0].impact == "high" and loaded.scan_complete is True


def test_dialogue_roundtrip(tmp_path: Path):
    ws = tmp_path
    wb = WorkbenchState(project_name="dialogue-test", source_path="./repo")
    save_workbench(ws, wb)
    append_dialogue(ws, DialogueTurn(role="user", content="第一条消息"))
    append_dialogue(ws, DialogueTurn(role="agent", content="第一条回复", item_id="si-1"))
    append_dialogue(ws, DialogueTurn(role="user", content="", slash_command="/focus 1"))
    loaded = load_workbench(ws)
    assert loaded is not None and len(loaded.dialogue) == 3
    assert loaded.dialogue[0].content == "第一条消息"
    assert loaded.dialogue[2].slash_command == "/focus 1"


def test_slash_command_full_set():
    commands = {"/list": "list", "/focus 3": "focus", "/search 缓存": "search",
                "/plan 1": "plan", "/expand 1": "expand", "/compare 1 4": "compare",
                "/merge 2 5": "merge", "/discard 8": "discard", "/save": "save",
                "/status": "status", "/exit": "exit"}
    for user_input, expected_cmd in commands.items():
        cmd, _, _ = parse_input(user_input)
        assert cmd == expected_cmd, f"Failed for {user_input}"


def test_plan_generation_flow():
    from onep.strategy.planner import STANDARD_PLAN_TEMPLATE, FULL_PLAN_APPENDIX
    standard = STANDARD_PLAN_TEMPLATE.format(
        title="Test Plan", file_location="test.py:1", tags="测试, 性能", impact="high",
        timestamp="2026-01-01", problem_description="问题", optimization_direction="方向",
        implementation_approach="方案", risk_assessment="风险", reference_solutions="参考",
    )
    assert "Test Plan" in standard and "## 问题描述" in standard and "## 风险评估" in standard
    full = FULL_PLAN_APPENDIX.format(pseudocode="p", data_comparison="d", priority_and_dependencies="prio")
    assert "## 伪代码 / 架构变更" in full and "## 数据对比" in full and "## 优先级与依赖" in full
