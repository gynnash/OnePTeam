"""SQLite source of truth for the OnePTeam Product Studio."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from onep.config import _config_dir
from onep.domain import Problem
from onep.studio.discovery_store import DiscoveryStoreMixin
from onep.studio.models import KnowledgeRecord, StudioState, new_id, now


def studio_database_path() -> Path:
    return _config_dir() / "studio.db"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class StudioStore(DiscoveryStoreMixin):
    """Normalized, versioned store; it never reads the old meta or Harness DBs."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or studio_database_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS studio_projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    idea TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    definition_json TEXT NOT NULL DEFAULT '{}',
                    baseline_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_projects_updated
                    ON studio_projects(updated_at DESC);

                CREATE TABLE IF NOT EXISTS discovery_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    current_round INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS discovery_rounds (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    answered_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(project_id, round_number),
                    FOREIGN KEY(session_id) REFERENCES discovery_sessions(id),
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS discovery_round_questions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    round_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    dimension TEXT NOT NULL,
                    question TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    question_type TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    recommended_answer TEXT NOT NULL DEFAULT '',
                    recommendation_reason TEXT NOT NULL DEFAULT '',
                    required INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    answered_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id),
                    FOREIGN KEY(round_id) REFERENCES discovery_rounds(id)
                );
                CREATE INDEX IF NOT EXISTS discovery_questions_project_round
                    ON discovery_round_questions(project_id, round_number);

                CREATE TABLE IF NOT EXISTS discovery_assessments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    round_id TEXT NOT NULL DEFAULT '',
                    round_number INTEGER NOT NULL,
                    ready_to_draft INTEGER NOT NULL,
                    readiness_score REAL NOT NULL,
                    coverage_json TEXT NOT NULL,
                    confirmed_facts_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    open_decisions_json TEXT NOT NULL,
                    conflicts_json TEXT NOT NULL,
                    risk_flags_json TEXT NOT NULL,
                    next_questions_json TEXT NOT NULL,
                    policy_blockers_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id),
                    FOREIGN KEY(session_id) REFERENCES discovery_sessions(id)
                );

                CREATE TABLE IF NOT EXISTS product_assumptions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    statement TEXT NOT NULL,
                    source TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolution TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS prd_validations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    blockers_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    issues_json TEXT NOT NULL,
                    follow_up_questions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS prd_feedback (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    feedback TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS prd_versions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    change_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(project_id, version),
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS studio_features (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    PRIMARY KEY(id, prd_version),
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS release_scopes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    feature_ids_json TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS change_proposals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    base_prd_version INTEGER NOT NULL,
                    request TEXT NOT NULL,
                    impact_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS execution_units (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    requirement_ids_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    expected_paths_json TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    strategy_reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    thread_id TEXT NOT NULL DEFAULT '',
                    plan_json TEXT NOT NULL DEFAULT '[]',
                    attempt INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS studio_evidence (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_version INTEGER NOT NULL,
                    release_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    execution_unit_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    trust TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS studio_artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );
                CREATE INDEX IF NOT EXISTS studio_artifacts_project_created
                    ON studio_artifacts(project_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response TEXT NOT NULL DEFAULT '',
                    thread_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    validity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    generalizable INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES studio_projects(id)
                );
                CREATE INDEX IF NOT EXISTS knowledge_project_updated
                    ON knowledge_records(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS knowledge_validity_type
                    ON knowledge_records(validity, type);

                CREATE TABLE IF NOT EXISTS knowledge_applications (
                    id TEXT PRIMARY KEY,
                    knowledge_id TEXT NOT NULL,
                    target_project_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    adopted_as TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL,
                    feedback TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(knowledge_id, target_project_id, feature_id, phase),
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records(id),
                    FOREIGN KEY(target_project_id) REFERENCES studio_projects(id)
                );

                CREATE TABLE IF NOT EXISTS article_model_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_base TEXT NOT NULL DEFAULT '',
                    parameters_json TEXT NOT NULL,
                    credential_ref TEXT NOT NULL DEFAULT '',
                    credential_configured INTEGER NOT NULL DEFAULT 0,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS article_source_packs (
                    id TEXT PRIMARY KEY,
                    project_ids_json TEXT NOT NULL,
                    knowledge_ids_json TEXT NOT NULL,
                    facts_json TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    replacements_json TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    source_pack_id TEXT NOT NULL,
                    model_profile_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_pack_id) REFERENCES article_source_packs(id),
                    FOREIGN KEY(model_profile_id) REFERENCES article_model_profiles(id)
                );

                CREATE TABLE IF NOT EXISTS article_drafts (
                    article_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    long_title TEXT NOT NULL,
                    long_markdown TEXT NOT NULL,
                    short_title TEXT NOT NULL,
                    short_markdown TEXT NOT NULL,
                    title_candidates_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    generation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(article_id, version),
                    FOREIGN KEY(article_id) REFERENCES articles(id)
                );

                CREATE TABLE IF NOT EXISTS article_claims (
                    id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    knowledge_ids_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(id)
                );

                CREATE TABLE IF NOT EXISTS studio_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS studio_actions (
                    action_id TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def action_result(self, action_id: str) -> dict[str, Any] | None:
        if not action_id:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM studio_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return _load(row[0], {}) if row else None

    def remember_action(
        self, action_id: str, response: dict[str, Any], connection=None
    ) -> None:
        if not action_id:
            return
        owns = connection is None
        connection = connection or self._connect()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO studio_actions VALUES (?, ?, ?)",
                (action_id, _json(response), now()),
            )
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def append_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        project_id: str = "",
        connection=None,
    ) -> int:
        owns = connection is None
        connection = connection or self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO studio_events(project_id,type,payload_json,created_at) "
                "VALUES(?,?,?,?)",
                (project_id, event_type, _json(payload), now()),
            )
            if owns:
                connection.commit()
            return int(cursor.lastrowid)
        finally:
            if owns:
                connection.close()

    def events(self, project_id: str = "", after: int = 0) -> list[dict[str, Any]]:
        query = "SELECT * FROM studio_events WHERE sequence > ?"
        values: list[Any] = [max(0, after)]
        if project_id:
            query += " AND project_id = ?"
            values.append(project_id)
        query += " ORDER BY sequence LIMIT 500"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "project_id": row["project_id"],
                "type": row["type"],
                "payload": _load(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_project(
        self,
        name: str,
        idea: str,
        workspace_path: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now()
        value = {
            "id": project_id or new_id("project"),
            "name": name,
            "idea": idea,
            "workspace_path": workspace_path,
            "state": StudioState.DISCOVERY.value,
            "definition": {},
            "baseline": {},
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO studio_projects VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    value["id"],
                    name,
                    idea,
                    workspace_path,
                    value["state"],
                    "{}",
                    "{}",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            self.append_event("project.created", value, value["id"], connection)
        return value

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise Problem("project_not_found", "Project not found", project_id)
        return self._project(row)

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self._project(row) for row in rows]

    def update_project(
        self,
        project_id: str,
        *,
        state: str | None = None,
        definition: dict[str, Any] | None = None,
        baseline: dict[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id)
        if expected_revision is not None and current["revision"] != expected_revision:
            raise Problem(
                "revision_conflict",
                "Project changed elsewhere",
                "Reload the Product Studio before retrying.",
                actionable=True,
            )
        next_state = state or current["state"]
        if next_state not in {value.value for value in StudioState}:
            raise Problem("invalid_state", "Invalid project state", next_state)
        timestamp = now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE studio_projects SET state=?,definition_json=?,baseline_json=?,"
                "revision=revision+1,updated_at=? WHERE id=?",
                (
                    next_state,
                    _json(current["definition"] if definition is None else definition),
                    _json(current["baseline"] if baseline is None else baseline),
                    timestamp,
                    project_id,
                ),
            )
            self.append_event(
                "project.state.changed", {"state": next_state}, project_id, connection
            )
        return self.get_project(project_id)

    @staticmethod
    def _project(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "idea": row["idea"],
            "workspace_path": row["workspace_path"],
            "state": row["state"],
            "definition": _load(row["definition_json"], {}),
            "baseline": _load(row["baseline_json"], {}),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_prd(
        self,
        project_id: str,
        document: dict[str, Any],
        *,
        change_summary: str = "",
        status: str = "review",
    ) -> dict[str, Any]:
        if status not in {"draft", "review"}:
            raise Problem("invalid_prd_status", "Invalid PRD creation status", status)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM prd_versions WHERE project_id=?",
                (project_id,),
            ).fetchone()
            version = int(row[0]) + 1
            prd_id = new_id("prd")
            timestamp = now()
            connection.execute(
                "UPDATE prd_versions SET status='superseded' "
                "WHERE project_id=? AND status IN ('draft','review')",
                (project_id,),
            )
            connection.execute(
                "INSERT INTO prd_versions VALUES(?,?,?,?,?,?,?,?)",
                (
                    prd_id,
                    project_id,
                    version,
                    status,
                    _json(document),
                    change_summary,
                    timestamp,
                    "",
                ),
            )
            for feature in document.get("features") or ():
                connection.execute(
                    "INSERT INTO studio_features VALUES(?,?,?,?)",
                    (str(feature["id"]), project_id, version, _json(feature)),
                )
            self.append_event(
                "prd.created",
                {"version": version, "prd_id": prd_id},
                project_id,
                connection,
            )
        return self.get_prd(project_id, version)

    def get_prd(self, project_id: str, version: int | None = None) -> dict[str, Any]:
        query = "SELECT * FROM prd_versions WHERE project_id=?"
        values: list[Any] = [project_id]
        if version is not None:
            query += " AND version=?"
            values.append(version)
        query += " ORDER BY version DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        if row is None:
            raise Problem("prd_not_found", "PRD not found", project_id)
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "version": row["version"],
            "status": row["status"],
            "document": _load(row["document_json"], {}),
            "change_summary": row["change_summary"],
            "created_at": row["created_at"],
            "approved_at": row["approved_at"],
        }

    def prd_versions(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM prd_versions WHERE project_id=? "
                    "ORDER BY version DESC",
                    (project_id,),
                )
            ]
        return [self.get_prd(project_id, version) for version in versions]

    def set_prd_status(
        self,
        project_id: str,
        version: int,
        status: str,
    ) -> dict[str, Any]:
        if status not in {"draft", "review", "approved", "superseded"}:
            raise Problem("invalid_prd_status", "Invalid PRD status", status)
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE prd_versions SET status=? WHERE project_id=? AND version=?",
                (status, project_id, version),
            )
            if cursor.rowcount != 1:
                raise Problem("prd_not_found", "PRD not found", str(version))
        return self.get_prd(project_id, version)

    def approve_prd(
        self, project_id: str, version: int, feature_ids: list[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prd = self.get_prd(project_id, version)
        if prd["status"] not in {"review", "approved"}:
            raise Problem("prd_not_reviewable", "PRD cannot be approved", str(version))
        validation = self.prd_validation(project_id, version)
        if validation is None or not validation["passed"]:
            raise Problem(
                "prd_validation_required",
                "PRD has unresolved validation blockers",
                "; ".join(
                    (validation or {}).get("blockers") or ("Run PRD validation",)
                ),
                actionable=True,
                suggested_actions=("resolve_prd_feedback", "revalidate_prd"),
            )
        assumptions = self.product_assumptions(project_id, version)
        blocking_assumptions = [
            item
            for item in assumptions
            if item["status"] == "rejected"
            or (
                item["status"] == "pending"
                and item["risk"] in {"high", "critical", "高", "严重"}
            )
        ]
        if blocking_assumptions:
            raise Problem(
                "prd_assumptions_unresolved",
                "Resolve high-risk or rejected PRD assumptions before approval",
                "; ".join(item["statement"] for item in blocking_assumptions)[:4000],
                actionable=True,
                suggested_actions=("resolve_assumptions", "revise_prd"),
            )
        available = {str(item["id"]) for item in prd["document"].get("features") or ()}
        selected = list(dict.fromkeys(feature_ids))
        if not selected or not set(selected).issubset(available):
            raise Problem(
                "invalid_release_scope",
                "Release must select PRD features",
                ", ".join(sorted(set(selected) - available)),
            )
        timestamp = now()
        release = {
            "id": new_id("release"),
            "project_id": project_id,
            "prd_version": version,
            "status": "approved",
            "feature_ids": selected,
            "approved_at": timestamp,
            "created_at": timestamp,
            "revision": 1,
        }
        with self.transaction() as connection:
            connection.execute(
                "UPDATE prd_versions SET status='superseded' "
                "WHERE project_id=? AND status='approved' AND version<>?",
                (project_id, version),
            )
            connection.execute(
                "UPDATE prd_versions SET status='approved',approved_at=? "
                "WHERE project_id=? AND version=?",
                (timestamp, project_id, version),
            )
            connection.execute(
                "UPDATE release_scopes SET status='superseded' "
                "WHERE project_id=? AND status='approved'",
                (project_id,),
            )
            connection.execute(
                "INSERT INTO release_scopes VALUES(?,?,?,?,?,?,?,?)",
                (
                    release["id"],
                    project_id,
                    version,
                    "approved",
                    _json(selected),
                    timestamp,
                    timestamp,
                    1,
                ),
            )
            connection.execute(
                "UPDATE studio_projects SET state='ready',revision=revision+1,"
                "updated_at=? WHERE id=?",
                (timestamp, project_id),
            )
            self.append_event(
                "prd.approved",
                {"version": version, "release": release},
                project_id,
                connection,
            )
        return self.get_prd(project_id, version), release

    def current_release(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM release_scopes WHERE project_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "prd_version": row["prd_version"],
            "status": row["status"],
            "feature_ids": _load(row["feature_ids_json"], []),
            "approved_at": row["approved_at"],
            "created_at": row["created_at"],
            "revision": row["revision"],
        }

    def create_change_proposal(
        self,
        project_id: str,
        base_prd_version: int,
        request: str,
        impact: dict[str, Any],
        status: str = "review",
    ) -> dict[str, Any]:
        value = {
            "id": new_id("change"),
            "project_id": project_id,
            "base_prd_version": base_prd_version,
            "request": request,
            "impact": impact,
            "status": status,
            "created_at": now(),
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO change_proposals VALUES(?,?,?,?,?,?,?)",
                (
                    value["id"],
                    project_id,
                    base_prd_version,
                    request,
                    _json(impact),
                    status,
                    value["created_at"],
                ),
            )
            connection.execute(
                "UPDATE studio_projects SET state='prd_review',revision=revision+1,"
                "updated_at=? WHERE id=?",
                (now(), project_id),
            )
            connection.execute(
                "UPDATE execution_units SET status='paused',updated_at=? "
                "WHERE project_id=? AND feature_id IN ({})".format(
                    ",".join("?" for _ in impact.get("affected_feature_ids") or ())
                    or "''"
                ),
                (now(), project_id, *(impact.get("affected_feature_ids") or ())),
            )
            self.append_event("change.proposed", value, project_id, connection)
        return value

    def change_proposals(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM change_proposals WHERE project_id=? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [{**dict(row), "impact": _load(row["impact_json"], {})} for row in rows]

    def replace_execution_units(
        self, project_id: str, release_id: str, units: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        timestamp = now()
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM execution_units WHERE project_id=? AND release_id=?",
                (project_id, release_id),
            )
            for unit in units:
                connection.execute(
                    """INSERT INTO execution_units
                    (id,project_id,release_id,feature_id,title,objective,
                     requirement_ids_json,acceptance_json,verification_json,dependencies_json,
                     expected_paths_json,strategy,strategy_reason,status,thread_id,
                     plan_json,attempt,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        unit["id"],
                        project_id,
                        release_id,
                        unit["feature_id"],
                        unit["title"],
                        unit["objective"],
                        _json(unit.get("requirement_ids") or []),
                        _json(unit.get("acceptance") or []),
                        _json(unit.get("verification_commands") or []),
                        _json(unit.get("dependencies") or []),
                        _json(unit.get("expected_paths") or []),
                        unit["strategy"],
                        unit.get("strategy_reason") or "",
                        unit.get("status") or "pending",
                        unit.get("thread_id") or "",
                        _json(unit.get("plan") or []),
                        int(unit.get("attempt") or 0),
                        timestamp,
                        timestamp,
                    ),
                )
            self.append_event(
                "execution.units.compiled",
                {"count": len(units), "release_id": release_id},
                project_id,
                connection,
            )
        return self.execution_units(project_id, release_id)

    def execution_units(
        self, project_id: str, release_id: str = ""
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM execution_units WHERE project_id=?"
        values: list[Any] = [project_id]
        if release_id:
            query += " AND release_id=?"
            values.append(release_id)
        # Units are inserted in the approved Feature Map order. Keep that stable for
        # the UI; dependency ordering is applied separately by the supervisor.
        query += " ORDER BY created_at,rowid"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._execution_unit(row) for row in rows]

    def update_execution_unit(self, unit_id: str, **changes) -> dict[str, Any]:
        allowed = {
            "strategy",
            "strategy_reason",
            "status",
            "thread_id",
            "plan",
            "attempt",
        }
        if set(changes) - allowed:
            raise ValueError("unsupported execution unit update")
        assignments = []
        values: list[Any] = []
        for key, value in changes.items():
            column = "plan_json" if key == "plan" else key
            assignments.append(f"{column}=?")
            values.append(_json(value) if key == "plan" else value)
        assignments.append("updated_at=?")
        values.extend((now(), unit_id))
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE execution_units SET {','.join(assignments)} WHERE id=?",
                values,
            )
            if cursor.rowcount != 1:
                raise Problem(
                    "execution_unit_not_found", "Execution unit not found", unit_id
                )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_units WHERE id=?", (unit_id,)
            ).fetchone()
        return self._execution_unit(row)

    @staticmethod
    def _execution_unit(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "release_id": row["release_id"],
            "feature_id": row["feature_id"],
            "title": row["title"],
            "objective": row["objective"],
            "requirement_ids": _load(row["requirement_ids_json"], []),
            "acceptance": _load(row["acceptance_json"], []),
            "verification_commands": _load(row["verification_json"], []),
            "dependencies": _load(row["dependencies_json"], []),
            "expected_paths": _load(row["expected_paths_json"], []),
            "strategy": row["strategy"],
            "strategy_reason": row["strategy_reason"],
            "status": row["status"],
            "thread_id": row["thread_id"],
            "plan": _load(row["plan_json"], []),
            "attempt": row["attempt"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def record_evidence(self, value: dict[str, Any]) -> dict[str, Any]:
        evidence = {"id": value.get("id") or new_id("evidence"), **value}
        evidence.setdefault("created_at", now())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO studio_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence["id"],
                    evidence["project_id"],
                    int(evidence.get("prd_version") or 0),
                    evidence.get("release_id") or "",
                    evidence.get("feature_id") or "",
                    evidence.get("execution_unit_id") or "",
                    evidence["kind"],
                    evidence.get("trust") or "candidate",
                    int(bool(evidence.get("passed"))),
                    evidence.get("fingerprint") or "",
                    _json(evidence.get("detail") or {}),
                    evidence["created_at"],
                ),
            )
        return evidence

    def evidence(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_evidence WHERE project_id=? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if key != "detail_json"},
                "passed": bool(row["passed"]),
                "detail": _load(row["detail_json"], {}),
            }
            for row in rows
        ]

    def put_artifact(
        self,
        project_id: str,
        kind: str,
        content: str,
        content_type: str = "text/plain",
    ) -> dict[str, Any]:
        artifact = {
            "id": new_id("artifact"),
            "project_id": project_id,
            "kind": kind[:100],
            "content": content[:24_000],
            "content_type": content_type[:100],
            "created_at": now(),
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO studio_artifacts VALUES(?,?,?,?,?,?)",
                (
                    artifact["id"],
                    artifact["project_id"],
                    artifact["kind"],
                    artifact["content"],
                    artifact["content_type"],
                    artifact["created_at"],
                ),
            )
        return artifact

    def artifacts(self, project_id: str) -> list[dict[str, Any]]:
        """Internal-only Artifact access; API v2 intentionally exposes no route."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_artifacts WHERE project_id=? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_interaction(self, value: dict[str, Any]) -> dict[str, Any]:
        interaction = {
            "id": value.get("id") or new_id("interaction"),
            **value,
            "status": "pending",
            "response": "",
            "revision": 1,
            "created_at": now(),
            "resolved_at": "",
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO interactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    interaction["id"],
                    interaction["project_id"],
                    interaction["kind"],
                    interaction["prompt"],
                    _json(interaction.get("options") or []),
                    "pending",
                    "",
                    interaction.get("thread_id") or "",
                    interaction.get("turn_id") or "",
                    1,
                    interaction["created_at"],
                    "",
                ),
            )
            self.append_event(
                "interaction.requested",
                interaction,
                interaction["project_id"],
                connection,
            )
        return interaction

    def resolve_interaction(
        self, interaction_id: str, response: str, expected_revision: int
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE interactions SET response=?,status='resolved',revision=revision+1,"
                "resolved_at=? WHERE id=? AND status='pending' AND revision=?",
                (response.strip(), now(), interaction_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise Problem(
                    "interaction_conflict",
                    "Interaction is stale or already resolved",
                    interaction_id,
                )
            row = connection.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
            value = self._interaction(row)
            self.append_event(
                "interaction.resolved",
                {"id": interaction_id},
                value["project_id"],
                connection,
            )
        return value

    def get_interaction(self, interaction_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction_id,)
            ).fetchone()
        if row is None:
            raise Problem(
                "interaction_not_found", "Interaction request not found", interaction_id
            )
        return self._interaction(row)

    def interactions(self, project_id: str, status: str = "") -> list[dict[str, Any]]:
        query = "SELECT * FROM interactions WHERE project_id=?"
        values: list[Any] = [project_id]
        if status:
            query += " AND status=?"
            values.append(status)
        query += " ORDER BY created_at"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._interaction(row) for row in rows]

    @staticmethod
    def _interaction(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["options"] = _load(value.pop("options_json"), [])
        return value

    def put_knowledge(self, record: KnowledgeRecord) -> dict[str, Any]:
        data = record.to_dict()
        search_text = " ".join(
            str(value)
            for value in (
                record.title,
                record.summary,
                record.problem_context,
                record.error_signature,
                record.root_cause,
                record.final_fix,
                record.problem_category,
                *record.technology_stack,
                *record.components,
                *record.tags,
            )
            if value
        ).lower()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO knowledge_records
                (id,project_id,type,title,summary,validity,confidence,generalizable,
                 data_json,search_text,revision,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                summary=excluded.summary,validity=excluded.validity,
                confidence=excluded.confidence,generalizable=excluded.generalizable,
                data_json=excluded.data_json,search_text=excluded.search_text,
                revision=knowledge_records.revision+1,updated_at=excluded.updated_at""",
                (
                    record.id,
                    record.project_id,
                    record.type,
                    record.title,
                    record.summary,
                    record.validity,
                    record.confidence,
                    int(record.generalizable),
                    _json(data),
                    search_text,
                    record.revision,
                    record.created_at,
                    now(),
                ),
            )
            self.append_event(
                "knowledge.recorded",
                {"knowledge_id": record.id, "type": record.type},
                record.project_id,
                connection,
            )
        return self.get_knowledge(record.id)

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_records WHERE id=?", (knowledge_id,)
            ).fetchone()
        if row is None:
            raise Problem(
                "knowledge_not_found", "Knowledge record not found", knowledge_id
            )
        data = _load(row["data_json"], {})
        data.update(
            revision=row["revision"],
            validity=row["validity"],
            confidence=row["confidence"],
            generalizable=bool(row["generalizable"]),
            updated_at=row["updated_at"],
        )
        return data

    def update_knowledge(
        self, knowledge_id: str, patch: dict[str, Any], expected_revision: int
    ) -> dict[str, Any]:
        current = self.get_knowledge(knowledge_id)
        if current["revision"] != expected_revision:
            raise Problem("revision_conflict", "Knowledge record changed elsewhere")
        allowed = {
            "title",
            "summary",
            "confidence",
            "generalizable",
            "validity",
            "tags",
            "components",
            "problem_category",
            "prevention",
        }
        unknown = set(patch) - allowed
        if unknown:
            raise Problem(
                "invalid_knowledge_patch",
                "Unsupported knowledge fields",
                ", ".join(unknown),
            )
        current.update(patch)
        current["revision"] += 1
        return self.put_knowledge(
            KnowledgeRecord(
                **{key: current[key] for key in KnowledgeRecord.__dataclass_fields__}
            )
        )

    def knowledge_rows(self, project_id: str = "") -> list[dict[str, Any]]:
        query = "SELECT id FROM knowledge_records"
        values: list[Any] = []
        if project_id:
            query += " WHERE project_id=?"
            values.append(project_id)
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            ids = [row[0] for row in connection.execute(query, values)]
        return [self.get_knowledge(value) for value in ids]

    def save_knowledge_application(self, value: dict[str, Any]) -> dict[str, Any]:
        timestamp = now()
        application = {
            "id": value.get("id") or new_id("knowledge_use"),
            **value,
            "feature_id": value.get("feature_id") or "",
            "adopted_as": value.get("adopted_as") or "",
            "result": value.get("result") or "pending",
            "feedback": value.get("feedback") or "",
            "created_at": value.get("created_at") or timestamp,
            "updated_at": timestamp,
        }
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO knowledge_applications VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(knowledge_id,target_project_id,feature_id,phase)
                DO UPDATE SET adopted_as=excluded.adopted_as,result=excluded.result,
                feedback=excluded.feedback,updated_at=excluded.updated_at""",
                (
                    application["id"],
                    application["knowledge_id"],
                    application["target_project_id"],
                    application["feature_id"],
                    application["phase"],
                    application["reason"],
                    application["adopted_as"],
                    application["result"],
                    application["feedback"],
                    application["created_at"],
                    timestamp,
                ),
            )
        return application

    def knowledge_applications(self, project_id: str = "") -> list[dict[str, Any]]:
        query = "SELECT * FROM knowledge_applications"
        values: list[Any] = []
        if project_id:
            query += " WHERE target_project_id=?"
            values.append(project_id)
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, values)]

    def studio_snapshot(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        try:
            prd = self.get_prd(project_id)
        except Problem:
            prd = None
        return {
            "project": project,
            "discovery": self.discovery_snapshot(project_id),
            "questions": self.discovery_questions(project_id),
            "prd": prd,
            "prd_versions": self.prd_versions(project_id),
            "prd_validation": self.prd_validation(
                project_id, prd["version"] if prd else None
            ),
            "assumptions": (
                self.product_assumptions(project_id, prd["version"]) if prd else []
            ),
            "release": self.current_release(project_id),
            "execution_units": self.execution_units(project_id),
            "interactions": self.interactions(project_id),
            "evidence": self.evidence(project_id),
            "knowledge": self.knowledge_rows(project_id),
            "knowledge_applications": self.knowledge_applications(project_id),
        }

    def save_article_model_profile(self, value: dict[str, Any]) -> dict[str, Any]:
        timestamp = now()
        profile_id = str(value.get("id") or new_id("article_model"))
        with self.transaction() as connection:
            if value.get("is_default"):
                connection.execute("UPDATE article_model_profiles SET is_default=0")
            existing = connection.execute(
                "SELECT * FROM article_model_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO article_model_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        profile_id,
                        value["name"],
                        value["provider"],
                        value["model"],
                        value.get("api_base") or "",
                        _json(value.get("parameters") or {}),
                        value.get("credential_ref") or "",
                        int(bool(value.get("credential_configured"))),
                        int(bool(value.get("is_default"))),
                        int(value.get("active", True)),
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                expected = value.get("expected_revision")
                if expected is not None and int(expected) != existing["revision"]:
                    raise Problem(
                        "revision_conflict", "Article model changed elsewhere"
                    )
                connection.execute(
                    """UPDATE article_model_profiles SET name=?,provider=?,model=?,
                    api_base=?,parameters_json=?,credential_ref=?,credential_configured=?,
                    is_default=?,active=?,revision=revision+1,updated_at=? WHERE id=?""",
                    (
                        value["name"],
                        value["provider"],
                        value["model"],
                        value.get("api_base") or "",
                        _json(value.get("parameters") or {}),
                        value.get("credential_ref") or existing["credential_ref"],
                        int(
                            bool(
                                value.get(
                                    "credential_configured",
                                    existing["credential_configured"],
                                )
                            )
                        ),
                        int(bool(value.get("is_default"))),
                        int(value.get("active", True)),
                        timestamp,
                        profile_id,
                    ),
                )
        return self.get_article_model_profile(profile_id)

    def get_article_model_profile(self, profile_id: str = "") -> dict[str, Any]:
        query = "SELECT * FROM article_model_profiles"
        values: list[Any] = []
        if profile_id:
            query += " WHERE id=?"
            values.append(profile_id)
        else:
            query += " WHERE is_default=1 AND active=1"
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        if row is None:
            raise Problem(
                "article_model_not_found",
                "Article model profile not found",
                profile_id or "Configure a default article model in Settings.",
                actionable=True,
                suggested_actions=("configure_article_model",),
            )
        return self._article_model(row)

    def article_model_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM article_model_profiles ORDER BY is_default DESC,name"
            ).fetchall()
        return [self._article_model(row) for row in rows]

    @staticmethod
    def _article_model(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "provider": row["provider"],
            "model": row["model"],
            "api_base": row["api_base"],
            "parameters": _load(row["parameters_json"], {}),
            "credential_ref": row["credential_ref"],
            "credential_configured": bool(row["credential_configured"]),
            "credential_mask": "••••••••" if row["credential_configured"] else "",
            "is_default": bool(row["is_default"]),
            "active": bool(row["active"]),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_article_model_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_article_model_profile(profile_id)
        with self.transaction() as connection:
            in_use = connection.execute(
                "SELECT 1 FROM articles WHERE model_profile_id=? LIMIT 1", (profile_id,)
            ).fetchone()
            if in_use:
                connection.execute(
                    "UPDATE article_model_profiles SET active=0,is_default=0,"
                    "revision=revision+1,updated_at=? WHERE id=?",
                    (now(), profile_id),
                )
                profile["active"] = False
            else:
                connection.execute(
                    "DELETE FROM article_model_profiles WHERE id=?", (profile_id,)
                )
                profile["deleted"] = True
        return profile

    def create_source_pack(self, value: dict[str, Any]) -> dict[str, Any]:
        pack = {
            "id": new_id("source_pack"),
            "project_ids": value["project_ids"],
            "knowledge_ids": value["knowledge_ids"],
            "facts": value["facts"],
            "risks": value.get("risks") or [],
            "replacements": value.get("replacements") or {},
            "confirmed": False,
            "revision": 1,
            "created_at": now(),
            "confirmed_at": "",
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO article_source_packs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    pack["id"],
                    _json(pack["project_ids"]),
                    _json(pack["knowledge_ids"]),
                    _json(pack["facts"]),
                    _json(pack["risks"]),
                    _json(pack["replacements"]),
                    0,
                    1,
                    pack["created_at"],
                    "",
                ),
            )
        return pack

    def get_source_pack(self, pack_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM article_source_packs WHERE id=?", (pack_id,)
            ).fetchone()
        if row is None:
            raise Problem(
                "source_pack_not_found", "Article source pack not found", pack_id
            )
        return {
            "id": row["id"],
            "project_ids": _load(row["project_ids_json"], []),
            "knowledge_ids": _load(row["knowledge_ids_json"], []),
            "facts": _load(row["facts_json"], []),
            "risks": _load(row["risks_json"], []),
            "replacements": _load(row["replacements_json"], {}),
            "confirmed": bool(row["confirmed"]),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "confirmed_at": row["confirmed_at"],
        }

    def confirm_source_pack(
        self, pack_id: str, expected_revision: int
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE article_source_packs SET confirmed=1,revision=revision+1,"
                "confirmed_at=? WHERE id=? AND revision=?",
                (now(), pack_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise Problem(
                    "revision_conflict", "Article source pack changed elsewhere"
                )
        return self.get_source_pack(pack_id)

    def create_article(
        self, brief: dict[str, Any], source_pack_id: str, model_profile_id: str
    ) -> dict[str, Any]:
        timestamp = now()
        article = {
            "id": new_id("article"),
            "title": str(brief.get("topic") or "技术复盘"),
            "brief": brief,
            "source_pack_id": source_pack_id,
            "model_profile_id": model_profile_id,
            "status": "draft",
            "current_version": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    article["id"],
                    article["title"],
                    _json(brief),
                    source_pack_id,
                    model_profile_id,
                    "draft",
                    0,
                    timestamp,
                    timestamp,
                ),
            )
        return article

    def add_article_draft(
        self, article_id: str, draft: dict[str, Any], claims: list[dict[str, Any]]
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT current_version FROM articles WHERE id=?", (article_id,)
            ).fetchone()
            if row is None:
                raise Problem("article_not_found", "Article not found", article_id)
            version = int(row[0]) + 1
            timestamp = now()
            connection.execute(
                "INSERT INTO article_drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    article_id,
                    version,
                    draft["long_title"],
                    draft["long_markdown"],
                    draft["short_title"],
                    draft["short_markdown"],
                    _json(draft.get("title_candidates") or []),
                    _json(draft.get("topics") or []),
                    _json(draft.get("generation") or {}),
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE articles SET title=?,status=?,current_version=?,updated_at=? "
                "WHERE id=?",
                (
                    draft["long_title"],
                    draft.get("status") or "draft",
                    version,
                    timestamp,
                    article_id,
                ),
            )
            for claim in claims:
                connection.execute(
                    "INSERT INTO article_claims VALUES(?,?,?,?,?,?,?,?)",
                    (
                        new_id("claim"),
                        article_id,
                        version,
                        claim.get("platform") or "both",
                        claim["claim"],
                        _json(claim.get("knowledge_ids") or []),
                        _json(claim.get("evidence_ids") or []),
                        claim.get("status") or "supported",
                    ),
                )
        return self.get_article(article_id, version)

    def get_article(
        self, article_id: str, version: int | None = None
    ) -> dict[str, Any]:
        with self._connect() as connection:
            article_row = connection.execute(
                "SELECT * FROM articles WHERE id=?", (article_id,)
            ).fetchone()
            if article_row is None:
                raise Problem("article_not_found", "Article not found", article_id)
            selected = int(version or article_row["current_version"])
            draft_row = connection.execute(
                "SELECT * FROM article_drafts WHERE article_id=? AND version=?",
                (article_id, selected),
            ).fetchone()
            claims = connection.execute(
                "SELECT * FROM article_claims WHERE article_id=? AND version=?",
                (article_id, selected),
            ).fetchall()
            versions = [
                {
                    "version": row["version"],
                    "long_title": row["long_title"],
                    "short_title": row["short_title"],
                    "created_at": row["created_at"],
                }
                for row in connection.execute(
                    "SELECT version,long_title,short_title,created_at FROM article_drafts "
                    "WHERE article_id=? ORDER BY version DESC",
                    (article_id,),
                )
            ]
        article = dict(article_row)
        article["brief"] = _load(article.pop("brief_json"), {})
        article["selected_version"] = selected
        article["versions"] = versions
        if draft_row is None:
            article["draft"] = None
            article["claims"] = []
            return article
        article["draft"] = {
            "version": draft_row["version"],
            "long_title": draft_row["long_title"],
            "long_markdown": draft_row["long_markdown"],
            "short_title": draft_row["short_title"],
            "short_markdown": draft_row["short_markdown"],
            "title_candidates": _load(draft_row["title_candidates_json"], []),
            "topics": _load(draft_row["topics_json"], []),
            "generation": _load(draft_row["generation_json"], {}),
            "created_at": draft_row["created_at"],
        }
        article["claims"] = [
            {
                "id": row["id"],
                "platform": row["platform"],
                "claim": row["claim"],
                "knowledge_ids": _load(row["knowledge_ids_json"], []),
                "evidence_ids": _load(row["evidence_ids_json"], []),
                "status": row["status"],
            }
            for row in claims
        ]
        return article

    def articles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM articles ORDER BY updated_at DESC"
                )
            ]
        return [self.get_article(article_id) for article_id in ids]
