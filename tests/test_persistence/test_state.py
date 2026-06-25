from pathlib import Path

from onep.persistence.state import load_state, save_state
from onep.persistence.models import PipelineState, ProjectMode


def test_save_and_load_state(tmp_path: Path):
    state = PipelineState(
        mode=ProjectMode("greenfield"),
        current_stage="architect",
        stages_completed=["pm", "designer"],
        artifacts={"prd": "docs/PRD.md"},
    )
    save_state(tmp_path, state)

    loaded = load_state(tmp_path)
    assert loaded.mode == "greenfield"
    assert loaded.current_stage == "architect"
    assert loaded.stages_completed == ["pm", "designer"]
    assert loaded.artifacts["prd"] == "docs/PRD.md"


def test_load_state_returns_default_for_missing(tmp_path: Path):
    state = load_state(tmp_path)
    assert state.mode == "greenfield"
    assert state.stages_completed == []
