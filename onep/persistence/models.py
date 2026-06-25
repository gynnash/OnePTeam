"""Dataclass models for projects, stages, and pipeline state."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ProjectMode(str, Enum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class ProjectStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class StageRun:
    """Record of a single pipeline stage execution."""
    project_id: str
    stage_name: str
    agent_name: str
    status: StageStatus = StageStatus.PENDING
    model_used: str = ""
    token_count: int = 0
    output_files: list[str] = field(default_factory=list)
    error_message: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = ""
    finished_at: str = ""

    def start(self) -> None:
        self.status = StageStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc).isoformat()

    def complete(self, output_files: list[str], token_count: int = 0) -> None:
        self.status = StageStatus.COMPLETED
        self.output_files = output_files
        self.token_count = token_count
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def fail(self, error: str) -> None:
        self.status = StageStatus.FAILED
        self.error_message = error
        self.finished_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Approval:
    """Record of a user approval/rejection."""
    stage_run_id: str
    decision: Decision
    feedback: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Project:
    """A managed software project."""
    name: str
    mode: ProjectMode
    workspace_path: str
    status: ProjectStatus = ProjectStatus.RUNNING
    current_stage: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class PipelineState:
    """Runtime pipeline state mirrored in state.yaml."""
    mode: ProjectMode = ProjectMode.GREENFIELD
    current_stage: str = ""
    stages_completed: list[str] = field(default_factory=list)
    pending_approval: bool = False
    langgraph_checkpoint_id: str = ""
    retry_attempts: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
