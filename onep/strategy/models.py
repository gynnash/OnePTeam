"""Data models for strategy analysis: items, dialogue turns, and plan versions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ItemStatus(str, Enum):
    PENDING = "pending"
    DISCUSSING = "discussing"
    PLAN_DRAFTED = "plan_drafted"
    PLAN_REVIEWED = "plan_reviewed"
    DISCARDED = "discarded"


class PlanVersion(str, Enum):
    NONE = "none"
    STANDARD = "standard"
    FULL = "full"


@dataclass
class StrategyItem:
    """A single optimization direction discovered during analysis."""
    title: str
    file_location: str
    summary: str = ""
    impact: str = "medium"
    tags: list[str] = field(default_factory=list)
    status: ItemStatus = ItemStatus.PENDING
    discussion_summary: str = ""
    plan_path: str | None = None
    plan_version: PlanVersion = PlanVersion.NONE
    id: str = field(default_factory=lambda: f"si-{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def start_discussing(self) -> None:
        self.status = ItemStatus.DISCUSSING
        self.touch()

    def draft_plan(self, plan_path: str) -> None:
        self.status = ItemStatus.PLAN_DRAFTED
        self.plan_path = plan_path
        self.plan_version = PlanVersion.STANDARD
        self.touch()

    def review_plan(self) -> None:
        self.status = ItemStatus.PLAN_REVIEWED
        self.touch()

    def expand_plan(self) -> None:
        self.plan_version = PlanVersion.FULL
        self.touch()

    def discard(self) -> None:
        self.status = ItemStatus.DISCARDED
        self.touch()


@dataclass
class DialogueTurn:
    """A single round in the strategy dialogue."""
    role: str
    content: str
    item_id: str | None = None
    slash_command: str | None = None
    id: str = field(default_factory=lambda: f"dt-{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkbenchState:
    """Top-level state for a strategy analysis session."""
    project_name: str
    source_path: str
    items: list[StrategyItem] = field(default_factory=list)
    dialogue: list[DialogueTurn] = field(default_factory=list)
    current_item_id: str | None = None
    scan_complete: bool = False
    analysis_complete: bool = False
