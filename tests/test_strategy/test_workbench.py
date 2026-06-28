from pathlib import Path
from onep.strategy.models import WorkbenchState, StrategyItem, ItemStatus, PlanVersion
from onep.strategy.workbench import (
    parse_input, _resolve_item_id, _find_item, _higher_impact,
    handle_slash_command, _build_dialogue_context, _cmd_read,
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


def test_dialogue_context_uses_project_aware_memory(tmp_path, monkeypatch):
    item = StrategyItem(title="Cache", file_location="cache.py:1", tags=["缓存"])
    wb = WorkbenchState(
        project_name="demo", source_path=str(tmp_path), items=[item],
        current_item_id=item.id,
    )
    captured = {}

    def build(self, request):
        captured["request"] = request
        return "<relevant_memories>known</relevant_memories>"

    monkeypatch.setattr(
        "onep.strategy.workbench.MemoryContextBuilder.build", build
    )

    context = _build_dialogue_context(wb, "如何优化")

    assert "<relevant_memories>" in context
    assert captured["request"].source_id == "brownfield:demo"
    assert "如何优化" in captured["request"].query


def test_full_plan_requires_reviewed_status(tmp_path):
    standard = tmp_path / "standard.md"
    standard.write_text("# Standard")
    item = StrategyItem(title="Cache", file_location="cache.py:1")
    item.draft_plan(str(standard))
    wb = WorkbenchState("demo", str(tmp_path), items=[item])

    handle_slash_command("expand", "1", wb, tmp_path, llm_adapter=object())

    assert item.plan_version == PlanVersion.STANDARD


def test_approve_marks_standard_plan_reviewed(tmp_path):
    standard = tmp_path / "standard.md"
    standard.write_text("# Standard")
    item = StrategyItem(title="Cache", file_location="cache.py:1")
    item.draft_plan(str(standard))
    wb = WorkbenchState("demo", str(tmp_path), items=[item])

    handle_slash_command("approve", "1", wb, tmp_path)

    assert item.status == ItemStatus.PLAN_REVIEWED


def test_read_rejects_path_outside_source_root(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    wb = WorkbenchState("demo", str(source))

    _cmd_read("../secret.txt", wb)

    assert "路径超出源码范围" in capsys.readouterr().out


def test_workbench_export_writes_inside_workspace(tmp_path):
    from tests.test_strategy.reporting_fakes import make_workbench_with_item

    wb = make_workbench_with_item(tmp_path)
    handle_slash_command("export", "reports/analysis.md", wb, tmp_path)
    assert (tmp_path / "reports" / "analysis.md").exists()


def test_workbench_export_rejects_parent_path(tmp_path, capsys):
    from tests.test_strategy.reporting_fakes import make_workbench_with_item

    wb = make_workbench_with_item(tmp_path)
    handle_slash_command("export", "../outside.md", wb, tmp_path)
    assert "路径超出" in capsys.readouterr().out
