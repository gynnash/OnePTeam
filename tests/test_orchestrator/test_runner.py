from pathlib import Path

from onep.orchestrator.runner import (
    _detect_output_files,
    _build_stage_prompt,
    _stage_result_error,
)
from onep.persistence.models import Project, ProjectMode


def test_detect_output_files_pm(tmp_path: Path):
    ws = tmp_path
    (ws / "docs").mkdir(parents=True)
    (ws / "docs" / "PRD.md").write_text("# PRD")
    files = _detect_output_files(ws, "pm")
    assert "docs/PRD.md" in files


def test_detect_output_files_empty(tmp_path: Path):
    files = _detect_output_files(tmp_path, "pm")
    assert files == []


def test_stage_prompt_includes_project_memory(tmp_path, monkeypatch):
    project = Project(
        name="demo",
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(tmp_path),
        requirement="Build notes",
    )
    captured = {}

    def build(self, request):
        captured["request"] = request
        return "<relevant_memories>known decision</relevant_memories>"

    monkeypatch.setattr(
        "onep.orchestrator.runner.MemoryContextBuilder.build", build
    )

    prompt = _build_stage_prompt(
        "pm", project, tmp_path, "", "", ""
    )

    assert "<relevant_memories>" in prompt
    assert captured["request"].source_id == "greenfield:demo"
    assert captured["request"].stage_name == "pm"


def test_empty_llm_response_is_stage_error():
    assert _stage_result_error("pm", None) == "LLM returned no output"


def test_failed_subflow_is_stage_error():
    assert _stage_result_error(
        "developer", "generated", subflow_passed=False
    ) == "developer validation failed"


def test_successful_stage_has_no_error():
    assert _stage_result_error(
        "developer", "generated", subflow_passed=True
    ) is None
