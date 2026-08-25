"""SQLite operations for adaptive Discovery and PRD validation."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from onep.domain import Problem
from onep.studio.models import new_id, now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class DiscoveryStoreMixin:
    """Keeps multi-round product discovery separate from the main store module."""

    def create_discovery_session(self, project_id: str) -> dict[str, Any]:
        timestamp = now()
        session = {
            "id": new_id("discovery"),
            "project_id": project_id,
            "status": "active",
            "current_round": 0,
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO discovery_sessions VALUES(?,?,?,?,?,?,?)",
                tuple(session.values()),
            )
            self.append_event("discovery.started", session, project_id, connection)
        return session

    def discovery_session(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM discovery_sessions WHERE project_id=?", (project_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def update_discovery_session(
        self,
        project_id: str,
        *,
        status: str | None = None,
        current_round: int | None = None,
    ) -> dict[str, Any]:
        session = self.discovery_session(project_id)
        if session is None:
            raise Problem(
                "discovery_not_found", "Discovery session not found", project_id
            )
        next_status = status or session["status"]
        if next_status not in {"active", "checkpoint", "ready", "completed"}:
            raise Problem(
                "invalid_discovery_status", "Invalid Discovery status", next_status
            )
        next_round = (
            session["current_round"] if current_round is None else current_round
        )
        with self.transaction() as connection:
            connection.execute(
                "UPDATE discovery_sessions SET status=?,current_round=?,"
                "revision=revision+1,updated_at=? WHERE project_id=?",
                (next_status, next_round, now(), project_id),
            )
            self.append_event(
                "discovery.status.changed",
                {"status": next_status, "current_round": next_round},
                project_id,
                connection,
            )
        return self.discovery_session(project_id) or session

    def create_discovery_round(
        self,
        project_id: str,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        session = self.discovery_session(project_id)
        if session is None:
            session = self.create_discovery_session(project_id)
        round_number = int(session["current_round"]) + 1
        timestamp = now()
        round_value = {
            "id": new_id("round"),
            "session_id": session["id"],
            "project_id": project_id,
            "round_number": round_number,
            "status": "pending",
            "created_at": timestamp,
            "answered_at": "",
        }
        values = []
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO discovery_rounds VALUES(?,?,?,?,?,?,?)",
                tuple(round_value.values()),
            )
            for item in questions[:3]:
                question = {
                    "id": new_id("question"),
                    "project_id": project_id,
                    "round_id": round_value["id"],
                    "round_number": round_number,
                    "dimension": str(item.get("dimension") or "product_scope")[:100],
                    "question": str(item.get("question") or "")[:1000],
                    "impact": str(item.get("impact") or "")[:1000],
                    "question_type": str(
                        item.get("question_type") or item.get("type") or "free_text"
                    ),
                    "options": list(item.get("options") or ()),
                    "recommended_answer": str(item.get("recommended_answer") or "")[
                        :2000
                    ],
                    "recommendation_reason": str(
                        item.get("recommendation_reason") or ""
                    )[:1000],
                    "required": bool(item.get("required", True)),
                    "status": "pending",
                    "answer": "",
                    "created_at": timestamp,
                    "answered_at": "",
                }
                connection.execute(
                    """INSERT INTO discovery_round_questions
                    (id,project_id,round_id,round_number,dimension,question,impact,
                     question_type,options_json,recommended_answer,recommendation_reason,
                     required,status,answer,created_at,answered_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        question["id"],
                        project_id,
                        round_value["id"],
                        round_number,
                        question["dimension"],
                        question["question"],
                        question["impact"],
                        question["question_type"],
                        _json(question["options"]),
                        question["recommended_answer"],
                        question["recommendation_reason"],
                        int(question["required"]),
                        "pending",
                        "",
                        timestamp,
                        "",
                    ),
                )
                values.append(question)
            connection.execute(
                "UPDATE discovery_sessions SET status='active',current_round=?,"
                "revision=revision+1,updated_at=? WHERE project_id=?",
                (round_number, timestamp, project_id),
            )
            self.append_event(
                "discovery.round.created",
                {"round": round_number, "question_count": len(values)},
                project_id,
                connection,
            )
        return {**round_value, "questions": values}

    def discovery_rounds(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM discovery_rounds WHERE project_id=? ORDER BY round_number",
                (project_id,),
            ).fetchall()
        return [
            {**dict(row), "questions": self.discovery_questions(project_id, row["id"])}
            for row in rows
        ]

    def discovery_questions(
        self,
        project_id: str,
        round_id: str = "",
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM discovery_round_questions WHERE project_id=?"
        values: list[Any] = [project_id]
        if round_id:
            query += " AND round_id=?"
            values.append(round_id)
        query += " ORDER BY round_number,created_at,rowid"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._discovery_question(row) for row in rows]

    def answer_discovery_questions(
        self,
        project_id: str,
        answers: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not answers:
            raise Problem(
                "discovery_answers_required", "Answer the current Discovery round"
            )
        touched_rounds = set()
        with self.transaction() as connection:
            for answer in answers:
                text = str(answer.get("answer") or "").strip()
                if not text:
                    raise Problem(
                        "discovery_answer_required", "Discovery answers cannot be empty"
                    )
                question_id = str(answer.get("question_id") or "")
                row = connection.execute(
                    "SELECT round_id FROM discovery_round_questions "
                    "WHERE id=? AND project_id=? AND status='pending'",
                    (question_id, project_id),
                ).fetchone()
                if row is None:
                    raise Problem(
                        "question_not_found",
                        "Question not found or already answered",
                        question_id,
                    )
                touched_rounds.add(str(row["round_id"]))
                connection.execute(
                    "UPDATE discovery_round_questions SET answer=?,status='answered',"
                    "answered_at=? WHERE id=?",
                    (text[:8000], now(), question_id),
                )
            for round_id in touched_rounds:
                pending = connection.execute(
                    "SELECT COUNT(*) FROM discovery_round_questions "
                    "WHERE round_id=? AND status='pending'",
                    (round_id,),
                ).fetchone()[0]
                if pending == 0:
                    connection.execute(
                        "UPDATE discovery_rounds SET status='answered',answered_at=? WHERE id=?",
                        (now(), round_id),
                    )
            self.append_event(
                "discovery.answers.recorded",
                {"count": len(answers)},
                project_id,
                connection,
            )
        return self.discovery_questions(project_id)

    def save_discovery_assessment(
        self,
        project_id: str,
        round_id: str,
        round_number: int,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        assessment = {
            "id": new_id("assessment"),
            "project_id": project_id,
            "session_id": (self.discovery_session(project_id) or {})["id"],
            "round_id": round_id,
            "round_number": round_number,
            **value,
            "created_at": now(),
        }
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO discovery_assessments
                (id,project_id,session_id,round_id,round_number,ready_to_draft,
                 readiness_score,coverage_json,confirmed_facts_json,assumptions_json,
                 open_decisions_json,conflicts_json,risk_flags_json,next_questions_json,
                 policy_blockers_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    assessment["id"],
                    project_id,
                    assessment["session_id"],
                    round_id,
                    round_number,
                    int(bool(value.get("ready_to_draft"))),
                    float(value.get("readiness_score") or 0),
                    _json(value.get("coverage") or {}),
                    _json(value.get("confirmed_facts") or []),
                    _json(value.get("assumptions") or []),
                    _json(value.get("open_decisions") or []),
                    _json(value.get("conflicts") or []),
                    _json(value.get("risk_flags") or []),
                    _json(value.get("next_questions") or []),
                    _json(value.get("policy_blockers") or []),
                    assessment["created_at"],
                ),
            )
            self.append_event(
                "discovery.assessed",
                {
                    "assessment_id": assessment["id"],
                    "round": round_number,
                    "ready": bool(value.get("ready_to_draft")),
                },
                project_id,
                connection,
            )
        return self.discovery_assessment(project_id, assessment["id"])

    def discovery_assessment(
        self,
        project_id: str,
        assessment_id: str = "",
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM discovery_assessments WHERE project_id=?"
        values: list[Any] = [project_id]
        if assessment_id:
            query += " AND id=?"
            values.append(assessment_id)
        query += " ORDER BY round_number DESC,created_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        return self._assessment(row) if row is not None else None

    def discovery_assessments(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM discovery_assessments WHERE project_id=? "
                "ORDER BY round_number,created_at",
                (project_id,),
            ).fetchall()
        return [self._assessment(row) for row in rows]

    def discovery_snapshot(self, project_id: str) -> dict[str, Any]:
        questions = self.discovery_questions(project_id)
        return {
            "session": self.discovery_session(project_id),
            "rounds": self.discovery_rounds(project_id),
            "assessment": self.discovery_assessment(project_id),
            "assessments": self.discovery_assessments(project_id),
            "questions": questions,
            "pending_questions": [
                item for item in questions if item["status"] == "pending"
            ],
        }

    def create_product_assumptions(
        self,
        project_id: str,
        prd_version: int,
        assumptions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        timestamp = now()
        with self.transaction() as connection:
            for item in assumptions:
                statement = str(
                    item.get("statement") or item.get("assumption") or ""
                ).strip()
                if not statement:
                    continue
                connection.execute(
                    """INSERT INTO product_assumptions
                    (id,project_id,prd_version,statement,source,impact,risk,status,
                     resolution,revision,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(item.get("id") or new_id("assumption")),
                        project_id,
                        prd_version,
                        statement[:4000],
                        str(item.get("source") or "model")[:200],
                        str(item.get("impact") or "")[:2000],
                        str(item.get("risk") or "medium").lower()[:50],
                        "pending",
                        "",
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
        return self.product_assumptions(project_id, prd_version)

    def product_assumptions(
        self,
        project_id: str,
        prd_version: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM product_assumptions WHERE project_id=?"
        values: list[Any] = [project_id]
        if prd_version is not None:
            query += " AND prd_version=?"
            values.append(prd_version)
        query += " ORDER BY created_at"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, values)]

    def product_assumption(self, assumption_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM product_assumptions WHERE id=?", (assumption_id,)
            ).fetchone()
        if row is None:
            raise Problem("assumption_not_found", "Product assumption not found")
        return dict(row)

    def resolve_product_assumption(
        self,
        assumption_id: str,
        status: str,
        resolution: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if status not in {"accepted", "rejected", "replaced"}:
            raise Problem(
                "invalid_assumption_status", "Invalid assumption decision", status
            )
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE product_assumptions SET status=?,resolution=?,revision=revision+1,"
                "updated_at=? WHERE id=? AND revision=?",
                (status, resolution[:2000], now(), assumption_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise Problem(
                    "revision_conflict", "Product assumption changed elsewhere"
                )
            row = connection.execute(
                "SELECT * FROM product_assumptions WHERE id=?", (assumption_id,)
            ).fetchone()
            self.append_event(
                "prd.assumption.resolved",
                {"assumption_id": assumption_id, "status": status},
                row["project_id"],
                connection,
            )
        return dict(row)

    def save_prd_validation(
        self,
        project_id: str,
        prd_version: int,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        validation = {
            "id": new_id("prd_validation"),
            "project_id": project_id,
            "prd_version": prd_version,
            "passed": bool(value.get("passed")),
            "blockers": list(value.get("blockers") or ()),
            "warnings": list(value.get("warnings") or ()),
            "issues": list(value.get("issues") or ()),
            "follow_up_questions": list(value.get("follow_up_questions") or ()),
            "created_at": now(),
        }
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO prd_validations
                (id,project_id,prd_version,passed,blockers_json,warnings_json,
                 issues_json,follow_up_questions_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    validation["id"],
                    project_id,
                    prd_version,
                    int(validation["passed"]),
                    _json(validation["blockers"]),
                    _json(validation["warnings"]),
                    _json(validation["issues"]),
                    _json(validation["follow_up_questions"]),
                    validation["created_at"],
                ),
            )
            self.append_event(
                "prd.validated",
                {
                    "version": prd_version,
                    "passed": validation["passed"],
                    "blocker_count": len(validation["blockers"]),
                },
                project_id,
                connection,
            )
        return validation

    def prd_validation(
        self,
        project_id: str,
        prd_version: int | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM prd_validations WHERE project_id=?"
        values: list[Any] = [project_id]
        if prd_version is not None:
            query += " AND prd_version=?"
            values.append(prd_version)
        query += " ORDER BY prd_version DESC,created_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "prd_version": row["prd_version"],
            "passed": bool(row["passed"]),
            "blockers": _load(row["blockers_json"], []),
            "warnings": _load(row["warnings_json"], []),
            "issues": _load(row["issues_json"], []),
            "follow_up_questions": _load(row["follow_up_questions_json"], []),
            "created_at": row["created_at"],
        }

    def save_prd_feedback(
        self,
        project_id: str,
        prd_version: int,
        feedback: str,
    ) -> dict[str, Any]:
        value = {
            "id": new_id("prd_feedback"),
            "project_id": project_id,
            "prd_version": prd_version,
            "feedback": feedback[:8000],
            "created_at": now(),
        }
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO prd_feedback VALUES(?,?,?,?,?)", tuple(value.values())
            )
        return value

    @staticmethod
    def _discovery_question(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["options"] = _load(value.pop("options_json"), [])
        value["required"] = bool(value["required"])
        return value

    @staticmethod
    def _assessment(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["ready_to_draft"] = bool(value["ready_to_draft"])
        for key in (
            "coverage",
            "confirmed_facts",
            "assumptions",
            "open_decisions",
            "conflicts",
            "risk_flags",
            "next_questions",
            "policy_blockers",
        ):
            value[key] = _load(
                value.pop(f"{key}_json"), {} if key == "coverage" else []
            )
        return value
