"""Pipeline state machine with YAML checkpoint persistence."""
from __future__ import annotations

import enum
from pathlib import Path
import yaml


class Status(str, enum.Enum):
    INIT = "init"
    SCANNING = "scanning"
    SCAN_DONE = "scan_done"
    ANALYZING = "analyzing"
    ANALYZE_DONE = "analyze_done"
    DIALOGUE_ACTIVE = "dialogue_active"
    COMPLETED = "completed"
    FAILED = "failed"


class Layer(str, enum.Enum):
    SCAN = "scan"
    ANALYZE = "analyze"
    DIALOGUE = "dialogue"


class PipelineState:
    """State machine for the onep analyze pipeline. Persists to YAML."""

    def __init__(self, project_name: str = "", workspace: str = ""):
        self.project_name = project_name
        self.workspace = workspace
        self.status = Status.INIT
        self.current_layer: str = ""
        self.error: str = ""
        self.warning: str = ""
        self.scan_completed_batches: list[int] = []
        self.scan_failed_batches: list[dict] = []
        self.analysis_items_count: int = 0
        self.total_cost: float = 0.0

    @property
    def _state_path(self) -> Path:
        return Path(self.workspace) / "pipeline_state.yaml"

    def start_layer(self, layer: Layer) -> None:
        mapping = {
            Layer.SCAN: Status.SCANNING,
            Layer.ANALYZE: Status.ANALYZING,
            Layer.DIALOGUE: Status.DIALOGUE_ACTIVE,
        }
        self.status = mapping[layer]
        self.current_layer = layer.value
        self.error = ""
        self.warning = ""
        self.save()

    def complete_layer(self, layer: Layer) -> None:
        mapping = {
            Layer.SCAN: Status.SCAN_DONE,
            Layer.ANALYZE: Status.ANALYZE_DONE,
            Layer.DIALOGUE: Status.COMPLETED,
        }
        self.status = mapping[layer]
        self.save()

    def fail(self, error: str) -> None:
        self.status = Status.FAILED
        self.error = error
        self.save()

    def start_from(self, layer: Layer) -> None:
        """Skip to a specific layer (marks previous as done)."""
        if layer == Layer.ANALYZE:
            self.status = Status.SCAN_DONE
        elif layer == Layer.DIALOGUE:
            self.status = Status.ANALYZE_DONE
        self.start_layer(layer)

    def save(self) -> None:
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "project_name": self.project_name,
            "workspace": self.workspace,
            "status": self.status.value,
            "current_layer": self.current_layer,
            "error": self.error,
            "warning": self.warning,
            "scan_completed_batches": self.scan_completed_batches,
            "scan_failed_batches": self.scan_failed_batches,
            "analysis_items_count": self.analysis_items_count,
            "total_cost": self.total_cost,
        }
        path.write_text(yaml.dump(data, default_flow_style=False))

    @classmethod
    def load(cls, workspace: str) -> PipelineState | None:
        path = Path(workspace) / "pipeline_state.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        state = cls(
            project_name=data.get("project_name", ""),
            workspace=workspace,
        )
        state.status = Status(data.get("status", "init"))
        state.current_layer = data.get("current_layer", "")
        state.error = data.get("error", "")
        state.warning = data.get("warning", "")
        state.scan_completed_batches = data.get("scan_completed_batches", [])
        state.scan_failed_batches = data.get("scan_failed_batches", [])
        state.analysis_items_count = data.get("analysis_items_count", 0)
        state.total_cost = data.get("total_cost", 0.0)
        return state
