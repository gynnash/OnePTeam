from pathlib import Path

from onep.orchestrator.runner import _detect_output_files


def test_detect_output_files_pm(tmp_path: Path):
    ws = tmp_path
    (ws / "docs").mkdir(parents=True)
    (ws / "docs" / "PRD.md").write_text("# PRD")
    files = _detect_output_files(ws, "pm")
    assert "docs/PRD.md" in files


def test_detect_output_files_empty(tmp_path: Path):
    files = _detect_output_files(tmp_path, "pm")
    assert files == []
