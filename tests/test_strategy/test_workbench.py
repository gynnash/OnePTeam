from pathlib import Path
from onep.strategy.models import WorkbenchState, StrategyItem, ItemStatus
from onep.strategy.workbench import (
    parse_input, _resolve_item_id, _find_item, _higher_impact,
    handle_slash_command,
)


def test_parse_slash_command():
    cmd, args, msg = parse_input("/focus 3")
    assert cmd == "focus" and args == "3" and msg == ""


def test_parse_natural_language():
    cmd, args, msg = parse_input("展开说说第3个")
    assert cmd is None and args is None and msg == "展开说说第3个"


def test_parse_unknown_slash():
    cmd, args, msg = parse_input("/unknown_command test")
    assert cmd is None and args is None and msg == "/unknown_command test"


def test_resolve_item_id_numeric():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Test", file_location="f:1")
    wb.items.append(item)
    assert _resolve_item_id("1", wb) == item.id


def test_resolve_item_id_si_format():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Test", file_location="f:1")
    wb.items.append(item)
    assert _resolve_item_id(item.id, wb) == item.id


def test_resolve_item_id_skips_discarded():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    d1 = StrategyItem(title="Discarded", file_location="f:1"); d1.discard(); wb.items.append(d1)
    a1 = StrategyItem(title="Active", file_location="g:1"); wb.items.append(a1)
    assert _resolve_item_id("1", wb) == a1.id


def test_higher_impact():
    assert _higher_impact("high", "low") == "high"
    assert _higher_impact("low", "medium") == "medium"


def test_handle_slash_list(tmp_path):
    wb = WorkbenchState(project_name="test", source_path="./repo")
    wb.items.append(StrategyItem(title="A", file_location="a:1"))
    result = handle_slash_command("list", "", wb, tmp_path)
    assert result is wb


def test_handle_slash_discard(tmp_path):
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Remove Me", file_location="r:1")
    wb.items.append(item)
    handle_slash_command("discard", "1", wb, tmp_path)
    assert item.status == ItemStatus.DISCARDED
