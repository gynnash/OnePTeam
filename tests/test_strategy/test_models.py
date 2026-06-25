from onep.strategy.models import (
    StrategyItem, DialogueTurn, WorkbenchState,
    ItemStatus, PlanVersion,
)


def test_strategy_item_creation():
    item = StrategyItem(
        title="Cache invalidation strategy",
        file_location="cache.py:30",
        summary="Full refresh instead of incremental",
        impact="high",
        tags=["缓存策略", "性能"],
    )
    assert item.title == "Cache invalidation strategy"
    assert item.status == ItemStatus.PENDING
    assert item.plan_version == PlanVersion.NONE
    assert len(item.id) > 0


def test_strategy_item_lifecycle():
    item = StrategyItem(title="Test", file_location="f.py:1")
    item.start_discussing()
    assert item.status == ItemStatus.DISCUSSING
    item.draft_plan("plans/001-test.md")
    assert item.status == ItemStatus.PLAN_DRAFTED
    assert item.plan_version == PlanVersion.STANDARD
    item.review_plan()
    assert item.status == ItemStatus.PLAN_REVIEWED
    item.expand_plan()
    assert item.plan_version == PlanVersion.FULL
    item.discard()
    assert item.status == ItemStatus.DISCARDED


def test_dialogue_turn_creation():
    dt = DialogueTurn(role="user", content="展开说说第3个", item_id="si-3")
    assert dt.role == "user"
    assert dt.slash_command is None


def test_dialogue_turn_with_slash():
    dt = DialogueTurn(role="user", content="", slash_command="/focus 3")
    assert dt.slash_command == "/focus 3"


def test_workbench_state_defaults():
    wb = WorkbenchState(project_name="my-analysis", source_path="./repo")
    assert wb.scan_complete is False
    assert wb.analysis_complete is False
    assert wb.items == []
    assert wb.current_item_id is None
