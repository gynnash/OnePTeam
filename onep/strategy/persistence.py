"""Persistence for workbench state — YAML metadata + JSONL dialogue log."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from onep.strategy.models import WorkbenchState, StrategyItem, DialogueTurn, ItemStatus, PlanVersion


def _strategy_dir(workspace: Path) -> Path:
    return workspace / ".onep" / "strategy"


def _workbench_path(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "workbench.yaml"


def _dialogue_path(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "dialogue.jsonl"


def _plans_dir(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "plans"


def _serialize_item(item: StrategyItem) -> dict:
    return {
        "id": item.id, "title": item.title, "file_location": item.file_location,
        "summary": item.summary, "impact": item.impact, "tags": item.tags,
        "status": item.status.value, "discussion_summary": item.discussion_summary,
        "plan_path": item.plan_path, "plan_version": item.plan_version.value,
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _deserialize_item(data: dict) -> StrategyItem:
    return StrategyItem(
        id=data["id"], title=data["title"], file_location=data["file_location"],
        summary=data.get("summary", ""), impact=data.get("impact", "medium"),
        tags=data.get("tags", []), status=ItemStatus(data.get("status", "pending")),
        discussion_summary=data.get("discussion_summary", ""),
        plan_path=data.get("plan_path"),
        plan_version=PlanVersion(data.get("plan_version", "none")),
        created_at=data.get("created_at", ""), updated_at=data.get("updated_at", ""),
    )


def save_workbench(workspace: Path, wb: WorkbenchState) -> None:
    _strategy_dir(workspace).mkdir(parents=True, exist_ok=True)
    _plans_dir(workspace).mkdir(parents=True, exist_ok=True)
    raw = {
        "project_name": wb.project_name, "source_path": wb.source_path,
        "current_item_id": wb.current_item_id, "scan_complete": wb.scan_complete,
        "analysis_complete": wb.analysis_complete,
        "items": [_serialize_item(item) for item in wb.items],
    }
    _workbench_path(workspace).write_text(yaml.dump(raw, default_flow_style=False))


def load_workbench(workspace: Path) -> WorkbenchState | None:
    wb_path = _workbench_path(workspace)
    if not wb_path.exists():
        return None
    raw = yaml.safe_load(wb_path.read_text()) or {}
    items = [_deserialize_item(d) for d in raw.get("items", [])]
    dialogue = []
    dl_path = _dialogue_path(workspace)
    if dl_path.exists():
        for line in dl_path.read_text().strip().split("\n"):
            if line.strip():
                d = json.loads(line)
                dialogue.append(DialogueTurn(
                    id=d.get("id", ""), role=d["role"],
                    content=d.get("content", ""), item_id=d.get("item_id"),
                    slash_command=d.get("slash_command"), created_at=d.get("created_at", ""),
                ))
    return WorkbenchState(
        project_name=raw.get("project_name", ""),
        source_path=raw.get("source_path", ""),
        items=items, dialogue=dialogue,
        current_item_id=raw.get("current_item_id"),
        scan_complete=raw.get("scan_complete", False),
        analysis_complete=raw.get("analysis_complete", False),
    )


def append_dialogue(workspace: Path, turn: DialogueTurn) -> None:
    _strategy_dir(workspace).mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "id": turn.id, "role": turn.role, "content": turn.content,
        "item_id": turn.item_id, "slash_command": turn.slash_command,
        "created_at": turn.created_at,
    }, ensure_ascii=False)
    with open(_dialogue_path(workspace), "a") as f:
        f.write(line + "\n")


def save_plan(workspace: Path, plan_id: str, content: str) -> str:
    _plans_dir(workspace).mkdir(parents=True, exist_ok=True)
    plan_path = _plans_dir(workspace) / f"{plan_id}.md"
    plan_path.write_text(content)
    return str(plan_path)
