"""SQLite database operations for project metadata."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from onep.config import _config_dir
from onep.persistence.models import (
    Project,
    ProjectMode,
    ProjectStatus,
    StageRun,
    StageStatus,
    Approval,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT '',
    workspace_path TEXT NOT NULL,
    requirement TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL,
    model_used TEXT NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL DEFAULT 0,
    output_files TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    stage_run_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (stage_run_id) REFERENCES stage_runs(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""


def _db_path() -> Path:
    return _config_dir() / "meta.db"


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "requirement" not in columns:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN requirement TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()
    conn.close()


def insert_project(project: Project) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO projects (id, name, mode, status, current_stage, workspace_path, requirement, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project.id, project.name, project.mode.value, project.status.value,
         project.current_stage, project.workspace_path, project.requirement,
         project.created_at, project.updated_at),
    )
    conn.commit()
    conn.close()


def update_project(project: Project) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE projects SET status=?, current_stage=?, updated_at=? WHERE id=?",
        (project.status.value, project.current_stage, project.updated_at, project.id),
    )
    conn.commit()
    conn.close()


def get_project(project_id: str) -> Optional[Project]:
    conn = _connect()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return Project(
        id=row["id"], name=row["name"],
        mode=ProjectMode(row["mode"]), status=ProjectStatus(row["status"]),
        current_stage=row["current_stage"], workspace_path=row["workspace_path"],
        requirement=row["requirement"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def list_projects() -> list[Project]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [
        Project(
            id=r["id"], name=r["name"], mode=ProjectMode(r["mode"]),
            status=ProjectStatus(r["status"]), current_stage=r["current_stage"],
            workspace_path=r["workspace_path"], created_at=r["created_at"],
            requirement=r["requirement"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def insert_stage_run(sr: StageRun) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO stage_runs (id, project_id, stage_name, agent_name, status, model_used, token_count, output_files, error_message, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sr.id, sr.project_id, sr.stage_name, sr.agent_name, sr.status.value,
         sr.model_used, sr.token_count, json.dumps(sr.output_files),
         sr.error_message, sr.started_at, sr.finished_at),
    )
    conn.commit()
    conn.close()


def update_stage_run(sr: StageRun) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE stage_runs SET status=?, token_count=?, output_files=?, error_message=?, finished_at=? WHERE id=?",
        (sr.status.value, sr.token_count, json.dumps(sr.output_files),
         sr.error_message, sr.finished_at, sr.id),
    )
    conn.commit()
    conn.close()


def delete_project(project_id: str) -> bool:
    """Delete a project and its related records. Returns True if deleted."""
    conn = _connect()
    conn.execute("DELETE FROM conversations WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM approvals WHERE stage_run_id IN (SELECT id FROM stage_runs WHERE project_id=?)", (project_id,))
    conn.execute("DELETE FROM stage_runs WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    deleted = conn.total_changes > 0
    conn.commit()
    conn.close()
    return deleted


def get_latest_stage_run(
    project_id: str, stage_name: str
) -> Optional[StageRun]:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM stage_runs WHERE project_id=? AND stage_name=? "
        "ORDER BY started_at DESC LIMIT 1",
        (project_id, stage_name),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return StageRun(
        id=row["id"],
        project_id=row["project_id"],
        stage_name=row["stage_name"],
        agent_name=row["agent_name"],
        status=StageStatus(row["status"]),
        model_used=row["model_used"],
        token_count=row["token_count"],
        output_files=json.loads(row["output_files"]),
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def insert_approval(approval: Approval) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO approvals (id, stage_run_id, decision, feedback, created_at) VALUES (?, ?, ?, ?, ?)",
        (approval.id, approval.stage_run_id, approval.decision.value, approval.feedback, approval.created_at),
    )
    conn.commit()
    conn.close()
