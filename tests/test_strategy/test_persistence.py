from pathlib import Path

from onep.strategy.models import WorkbenchState, StrategyItem, DialogueTurn
from onep.strategy.persistence import (
    save_workbench, load_workbench, append_dialogue, save_plan,
)


def test_save_and_load_workbench(tmp_path: Path):
    ws = tmp_path
    wb = WorkbenchState(project_name="test", source_path="./repo")
    wb.items.append(StrategyItem(title="Test item", file_location="f.py:1", impact="high"))
    wb.items.append(StrategyItem(title="Another", file_location="g.py:10", tags=["缓存"]))
    wb.scan_complete = True
    save_workbench(ws, wb)
    loaded = load_workbench(ws)
    assert loaded is not None
    assert loaded.project_name == "test"
    assert loaded.scan_complete is True
    assert len(loaded.items) == 2
    assert loaded.items[0].title == "Test item"
    assert loaded.items[0].impact == "high"


def test_load_workbench_returns_none_for_missing(tmp_path: Path):
    ws = tmp_path
    assert load_workbench(ws) is None


def test_append_and_load_dialogue(tmp_path: Path):
    ws = tmp_path
    append_dialogue(ws, DialogueTurn(role="user", content="hello"))
    append_dialogue(ws, DialogueTurn(role="agent", content="你好！", item_id="si-1"))
    wb = WorkbenchState(project_name="test", source_path="./repo")
    save_workbench(ws, wb)
    loaded = load_workbench(ws)
    assert loaded is not None
    assert len(loaded.dialogue) == 2
    assert loaded.dialogue[0].role == "user"
    assert loaded.dialogue[1].item_id == "si-1"


def test_save_plan(tmp_path: Path):
    ws = tmp_path
    path = save_plan(ws, "001-test", "# Test Plan\n\nContent here.")
    assert path.endswith("001-test.md")
    assert Path(path).exists()
    assert "# Test Plan" in Path(path).read_text()
