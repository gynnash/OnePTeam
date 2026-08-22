"""SQLite WAL event store and durable job queue.

The implementation is deliberately one concrete class: both concerns require
the same transaction when a job changes state and emits an event.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from onep.domain import Job, JobStatus, Problem, RunRecord, RunStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ControlStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS v2_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    goal_version INTEGER NOT NULL,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS v2_jobs (
                    id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL,
                    mutating INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    lease_owner TEXT NOT NULL,
                    lease_until TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS v2_jobs_status_created
                    ON v2_jobs(status, created_at);
                CREATE INDEX IF NOT EXISTS v2_jobs_project_status
                    ON v2_jobs(project_id, status);
                CREATE TABLE IF NOT EXISTS v2_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS v2_events_run_sequence
                    ON v2_events(run_id, sequence);
                CREATE TABLE IF NOT EXISTS v2_workers (
                    id TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL
                );
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(v2_jobs)")
            }
            if "result_json" not in columns:
                connection.execute(
                    "ALTER TABLE v2_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'"
                )

    def append_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        project_id: str = "",
        run_id: str = "",
        connection: sqlite3.Connection | None = None,
    ) -> int:
        owns_connection = connection is None
        connection = connection or self._connect()
        try:
            cursor = connection.execute(
                """
                INSERT INTO v2_events
                    (project_id, run_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    run_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _now(),
                ),
            )
            if owns_connection:
                connection.commit()
            return int(cursor.lastrowid)
        finally:
            if owns_connection:
                connection.close()

    def events(
        self,
        *,
        after: int = 0,
        project_id: str = "",
        run_id: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses = ["sequence > ?"]
        values: list[Any] = [max(0, after)]
        if project_id:
            clauses.append("project_id = ?")
            values.append(project_id)
        if run_id:
            clauses.append("run_id = ?")
            values.append(run_id)
        values.append(min(max(1, limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM v2_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence LIMIT ?",
                values,
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "project_id": row["project_id"],
                "run_id": row["run_id"],
                "type": row["type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def enqueue_job(
        self,
        capability_id: str,
        payload: dict[str, Any],
        *,
        project_id: str = "",
        run_id: str = "",
        actor: str = "local-user",
        action_id: str,
        mutating: bool = True,
        trace_id: str = "",
    ) -> Job:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM v2_jobs WHERE action_id = ?", (action_id,)
            ).fetchone()
            if existing is not None:
                return self._job(existing)
            job_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO v2_jobs (
                    id, capability_id, payload_json, project_id, run_id,
                    actor, action_id, trace_id, mutating, status, attempts,
                    lease_owner, lease_until, error_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', '', '{}', ?, ?)
                """,
                (
                    job_id,
                    capability_id,
                    json.dumps(payload, ensure_ascii=False),
                    project_id,
                    run_id,
                    actor,
                    action_id,
                    trace_id,
                    int(mutating),
                    JobStatus.QUEUED.value,
                    now,
                    now,
                ),
            )
            self.append_event(
                "job.queued",
                {
                    "job_id": job_id,
                    "capability_id": capability_id,
                    "trace_id": trace_id,
                },
                project_id=project_id,
                run_id=run_id,
                connection=connection,
            )
            row = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._job(row)

    def claim_job(self, worker_id: str, lease_seconds: int = 30) -> Job | None:
        now = datetime.now(timezone.utc)
        lease_until = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._recover_expired(connection, now.isoformat())
            row = connection.execute(
                """
                SELECT candidate.*
                FROM v2_jobs candidate
                WHERE candidate.status = ?
                  AND (
                    candidate.mutating = 0
                    OR NOT EXISTS (
                        SELECT 1 FROM v2_jobs active
                        WHERE active.project_id = candidate.project_id
                          AND active.project_id != ''
                          AND active.mutating = 1
                          AND active.status IN (?, ?)
                    )
                  )
                ORDER BY candidate.created_at
                LIMIT 1
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.CANCEL_REQUESTED.value,
                ),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE v2_jobs
                SET status = ?, attempts = attempts + 1,
                    lease_owner = ?, lease_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.RUNNING.value,
                    worker_id,
                    lease_until,
                    now.isoformat(),
                    row["id"],
                ),
            )
            self.append_event(
                "job.started",
                {
                    "job_id": row["id"],
                    "capability_id": row["capability_id"],
                    "worker_id": worker_id,
                },
                project_id=row["project_id"],
                run_id=row["run_id"],
                connection=connection,
            )
            claimed = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        return self._job(claimed)

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 30) -> bool:
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=max(1, lease_seconds))
        ).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE v2_jobs SET lease_until = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND status = ?
                """,
                (
                    lease_until,
                    _now(),
                    job_id,
                    worker_id,
                    JobStatus.RUNNING.value,
                ),
            )
        return cursor.rowcount == 1

    def finish_job(
        self,
        job_id: str,
        *,
        succeeded: bool,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> Job:
        status = JobStatus.SUCCEEDED if succeeded else JobStatus.FAILED
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise Problem("job_not_found", "Job not found", job_id)
            if row["status"] == JobStatus.CANCEL_REQUESTED.value:
                status = JobStatus.CANCELLED
            connection.execute(
                """
                UPDATE v2_jobs
                SET status = ?, lease_owner = '', lease_until = '',
                    result_json = ?, error_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    json.dumps(result or {}, ensure_ascii=False, default=str),
                    json.dumps(error or {}, ensure_ascii=False),
                    _now(),
                    job_id,
                ),
            )
            self.append_event(
                f"job.{status.value}",
                {
                    "job_id": job_id,
                    "result": result or {},
                    "error": error or {},
                },
                project_id=row["project_id"],
                run_id=row["run_id"],
                connection=connection,
            )
            finished = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._job(finished)

    def request_cancel(self, job_id: str) -> Job:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise Problem("job_not_found", "Job not found", job_id)
            status = JobStatus(row["status"])
            if status == JobStatus.QUEUED:
                next_status = JobStatus.CANCELLED
            elif status == JobStatus.RUNNING:
                next_status = JobStatus.CANCEL_REQUESTED
            else:
                return self._job(row)
            connection.execute(
                "UPDATE v2_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (next_status.value, _now(), job_id),
            )
            self.append_event(
                "job.cancel_requested",
                {"job_id": job_id, "status": next_status.value},
                project_id=row["project_id"],
                run_id=row["run_id"],
                connection=connection,
            )
            updated = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._job(updated)

    def get_job(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM v2_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._job(row) if row is not None else None

    def jobs(self, limit: int = 50) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM v2_jobs ORDER BY created_at DESC LIMIT ?",
                (min(max(1, limit), 200),),
            ).fetchall()
        return [self._job(row) for row in rows]

    def has_active_jobs(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM v2_jobs
                WHERE status IN (?, ?, ?)
                LIMIT 1
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.CANCEL_REQUESTED.value,
                ),
            ).fetchone()
        return row is not None

    def is_cancel_requested(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and job.status in {
            JobStatus.CANCEL_REQUESTED,
            JobStatus.CANCELLED,
        })

    def worker_heartbeat(self, worker_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO v2_workers (id, last_seen) VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (worker_id, _now()),
            )

    def worker_health(self, stale_after: int = 10) -> dict[str, Any]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=max(1, stale_after))
        ).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, last_seen FROM v2_workers
                ORDER BY last_seen DESC LIMIT 1
                """
            ).fetchone()
        ready = bool(row and row["last_seen"] >= cutoff)
        return {
            "ready": ready,
            "worker_id": row["id"] if row else "",
            "last_seen": row["last_seen"] if row else "",
        }

    def create_run(self, run: RunRecord) -> RunRecord:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO v2_runs (
                    id, project_id, goal_version, workflow, status, stage,
                    options_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.project_id,
                    run.goal_version,
                    run.workflow,
                    run.status.value,
                    run.stage,
                    json.dumps(run.options, ensure_ascii=False),
                    run.created_at or now,
                    run.updated_at or now,
                ),
            )
        return self.get_run(run.id)

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM v2_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=row["id"],
            project_id=row["project_id"],
            goal_version=row["goal_version"],
            workflow=row["workflow"],
            status=RunStatus(row["status"]),
            stage=row["stage"],
            options=json.loads(row["options_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def latest_run_for_project(self, project_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM v2_runs
                WHERE project_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return self.get_run(row["id"]) if row is not None else None

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: str | None = None,
    ) -> RunRecord:
        assignments = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            assignments.append("status = ?")
            values.append(status.value)
        if stage is not None:
            assignments.append("stage = ?")
            values.append(stage)
        values.append(run_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE v2_runs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        if cursor.rowcount != 1:
            raise Problem("run_not_found", "Run not found", run_id)
        return self.get_run(run_id)

    @staticmethod
    def _recover_expired(
        connection: sqlite3.Connection, now: str
    ) -> None:
        connection.execute(
            """
            UPDATE v2_jobs
            SET status = ?, lease_owner = '', lease_until = '', updated_at = ?
            WHERE status = ? AND lease_until != '' AND lease_until < ?
            """,
            (
                JobStatus.QUEUED.value,
                now,
                JobStatus.RUNNING.value,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE v2_jobs
            SET status = ?, lease_owner = '', lease_until = '', updated_at = ?
            WHERE status = ? AND lease_until != '' AND lease_until < ?
            """,
            (
                JobStatus.CANCELLED.value,
                now,
                JobStatus.CANCEL_REQUESTED.value,
                now,
            ),
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            capability_id=row["capability_id"],
            payload=json.loads(row["payload_json"]),
            project_id=row["project_id"],
            run_id=row["run_id"],
            actor=row["actor"],
            action_id=row["action_id"],
            mutating=bool(row["mutating"]),
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            result=json.loads(row["result_json"]),
            error=json.loads(row["error_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
