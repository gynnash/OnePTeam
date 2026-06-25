"""Runtime pipeline state stored in project/.onep/state.yaml."""
from __future__ import annotations

from pathlib import Path
import yaml

from onep.persistence.models import PipelineState


def state_path(workspace: Path) -> Path:
    return workspace / ".onep" / "state.yaml"


def load_state(workspace: Path) -> PipelineState:
    sp = state_path(workspace)
    if not sp.exists():
        return PipelineState()
    raw = yaml.safe_load(sp.read_text()) or {}
    return PipelineState(
        mode=raw.get("mode", "greenfield"),
        current_stage=raw.get("current_stage", ""),
        stages_completed=raw.get("stages_completed", []),
        pending_approval=raw.get("pending_approval", False),
        langgraph_checkpoint_id=raw.get("langgraph_checkpoint_id", ""),
        retry_attempts=raw.get("retry_attempts", {}),
        artifacts=raw.get("artifacts", {}),
    )


def save_state(workspace: Path, state: PipelineState) -> None:
    sp = state_path(workspace)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.dump({
        "mode": state.mode,
        "current_stage": state.current_stage,
        "stages_completed": state.stages_completed,
        "pending_approval": state.pending_approval,
        "langgraph_checkpoint_id": state.langgraph_checkpoint_id,
        "retry_attempts": state.retry_attempts,
        "artifacts": state.artifacts,
    }, default_flow_style=False))
