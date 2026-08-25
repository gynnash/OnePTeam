"""Application flow for adaptive Discovery and PRD review."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from onep.domain import Problem
from onep.studio.discovery import (
    DiscoveryReadinessPolicy,
    raw_prd_structure_blockers,
    validate_prd,
)
from onep.studio.models import (
    DiscoveryAssessment,
    PRDValidation,
    PrdDocument,
    StudioState,
)
from onep.studio.product import normalize_prd


class ProductDiscoveryService:
    """Runs multi-round discovery without granting any code-write capability."""

    checkpoint_round = 3

    def __init__(self, store, product_model, knowledge, baseline_inspector) -> None:
        self.store = store
        self.product_model = product_model
        self.knowledge = knowledge
        self.baseline_inspector = baseline_inspector
        self.readiness = DiscoveryReadinessPolicy()

    def start(self, project: dict[str, Any]) -> dict[str, Any]:
        self.store.create_discovery_session(project["id"])
        assessment, context = self._assess(project, round_id="", round_number=0)
        if self.readiness.can_generate_prd(assessment):
            return self._create_prd(project, assessment, force_assumptions=False)
        self._open_next_round(project, assessment)
        return self._result(project["id"], knowledge_context=context)

    def answer(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        project = self.store.get_project(project_id)
        if project["state"] != StudioState.DISCOVERY.value:
            raise Problem(
                "discovery_closed", "Discovery is not active", project["state"]
            )
        answers = [
            dict(item)
            for item in payload.get("answers") or ()
            if isinstance(item, dict)
        ]
        self.store.answer_discovery_questions(project_id, answers)
        discovery = self.store.discovery_snapshot(project_id)
        if discovery["pending_questions"]:
            result = self._result(project_id)
            self.store.remember_action(action_id, result)
            return result
        session = discovery["session"] or {}
        current_round = int(session.get("current_round") or 0)
        rounds = discovery["rounds"]
        round_id = str(rounds[-1]["id"] if rounds else "")
        assessment, context = self._assess(
            project, round_id=round_id, round_number=current_round
        )
        if self.readiness.can_generate_prd(assessment):
            result = self._create_prd(project, assessment, force_assumptions=False)
        elif current_round >= self.checkpoint_round:
            self.store.update_discovery_session(project_id, status="checkpoint")
            result = self._result(project_id, knowledge_context=context)
        else:
            self._open_next_round(project, assessment)
            result = self._result(project_id, knowledge_context=context)
        self.store.remember_action(action_id, result)
        return result

    def decide(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        project = self.store.get_project(project_id)
        session = self.store.discovery_session(project_id)
        if project["state"] != StudioState.DISCOVERY.value or session is None:
            raise Problem(
                "discovery_closed", "Discovery is not active", project["state"]
            )
        discovery = self.store.discovery_snapshot(project_id)
        if session["status"] != "checkpoint" or discovery["pending_questions"]:
            raise Problem(
                "discovery_decision_not_available",
                "Discovery decisions are only available at a checkpoint",
                actionable=True,
                suggested_actions=("answer_current_round", "reassess"),
            )
        action = str(payload.get("action") or "").strip()
        assessment = self._latest_assessment(project_id)
        if action == "continue":
            self._open_next_round(project, assessment)
            result = self._result(project_id)
        elif action == "accept_recommendations":
            if not assessment.next_questions:
                raise Problem(
                    "discovery_recommendation_missing",
                    "No material system recommendation is available",
                    actionable=True,
                    suggested_actions=("draft_with_assumptions",),
                )
            missing_recommendation = next(
                (
                    item
                    for item in assessment.next_questions
                    if not item.recommended_answer.strip()
                ),
                None,
            )
            if missing_recommendation is not None:
                raise Problem(
                    "discovery_recommendation_missing",
                    "Not every pending question has a system recommendation",
                    missing_recommendation.question,
                    actionable=True,
                    suggested_actions=("continue", "draft_with_assumptions"),
                )
            round_value = self._open_next_round(project, assessment)
            answers = []
            for question in round_value["questions"]:
                recommendation = str(question.get("recommended_answer") or "").strip()
                answers.append(
                    {
                        "question_id": question["id"],
                        "answer": f"[采用系统建议] {recommendation}",
                    }
                )
            self.knowledge.capture_decision(
                project_id=project_id,
                title="采用 Discovery 系统建议",
                selected="; ".join(item["answer"] for item in answers),
                reason="用户在 Discovery Checkpoint 明确采用建议",
                options=("继续澄清", "采用系统建议", "带假设生成草稿"),
            )
            result = self.answer(project_id, {"answers": answers})
        elif action == "draft_with_assumptions":
            self.knowledge.capture_decision(
                project_id=project_id,
                title="带明确假设生成 PRD 草稿",
                selected="生成草稿",
                reason=str(payload.get("reason") or "用户选择先评审草稿"),
                options=("继续澄清", "采用系统建议", "带假设生成草稿"),
            )
            result = self._create_prd(project, assessment, force_assumptions=True)
        else:
            raise Problem(
                "invalid_discovery_decision", "Invalid Discovery decision", action
            )
        self.store.remember_action(action_id, result)
        return result

    def feedback_prd(
        self,
        project_id: str,
        version: int,
        payload: dict[str, Any],
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        feedback = str(payload.get("feedback") or "").strip()
        if not feedback:
            raise Problem("prd_feedback_required", "Describe the PRD correction")
        previous = self.store.get_prd(project_id, version)
        self.store.save_prd_feedback(project_id, version, feedback)
        project = self.store.get_project(project_id)
        assessment = self._latest_assessment(project_id)
        result = self._create_prd(
            project,
            assessment,
            force_assumptions=True,
            change_request=feedback,
            previous_prd=previous["document"],
        )
        self.knowledge.capture_decision(
            project_id=project_id,
            title=f"修订 PRD v{version}",
            selected=f"PRD v{result['prd']['version']}",
            reason=feedback,
            options=(f"保留 v{version}", "根据反馈生成新版本"),
            prd_version=result["prd"]["version"],
        )
        self.store.remember_action(action_id, result)
        return result

    def revalidate_prd(self, project_id: str, version: int) -> dict[str, Any]:
        prd = self.store.get_prd(project_id, version)
        assessment = self._latest_assessment(project_id)
        document = normalize_prd(
            prd["document"],
            self.baseline_inspector.inspect(
                self.store.get_project(project_id)["workspace_path"]
            ),
        )
        structural_blockers = tuple(
            str(item)
            for item in document.validation_summary.get("structural_blockers") or ()
        )
        validation = self._validate(
            project_id,
            document,
            assessment,
            structural_blockers=structural_blockers,
        )
        stored = self.store.save_prd_validation(
            project_id, version, validation.to_dict()
        )
        if stored["passed"] and prd["status"] == "draft":
            self.store.set_prd_status(project_id, version, "review")
            self.store.update_project(project_id, state=StudioState.PRD_REVIEW.value)
        return stored

    def reassess(
        self,
        project_id: str,
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        project = self.store.get_project(project_id)
        discovery = self.store.discovery_snapshot(project_id)
        if project["state"] != StudioState.DISCOVERY.value:
            raise Problem(
                "discovery_closed", "Discovery is not active", project["state"]
            )
        if discovery["pending_questions"]:
            raise Problem(
                "discovery_answers_required", "Answer the current Discovery round first"
            )
        session = discovery["session"] or {}
        current_round = int(session.get("current_round") or 0)
        rounds = discovery["rounds"]
        assessment, context = self._assess(
            project,
            round_id=str(rounds[-1]["id"] if rounds else ""),
            round_number=current_round,
        )
        if self.readiness.can_generate_prd(assessment):
            result = self._create_prd(project, assessment, force_assumptions=False)
        elif current_round >= self.checkpoint_round:
            self.store.update_discovery_session(project_id, status="checkpoint")
            result = self._result(project_id, knowledge_context=context)
        else:
            self._open_next_round(project, assessment)
            result = self._result(project_id, knowledge_context=context)
        self.store.remember_action(action_id, result)
        return result

    def resolve_assumption(
        self,
        project_id: str,
        version: int,
        assumption_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.store.product_assumption(assumption_id)
        if current["project_id"] != project_id or current["prd_version"] != version:
            raise Problem(
                "assumption_not_found", "Assumption does not belong to this PRD"
            )
        assumption = self.store.resolve_product_assumption(
            assumption_id,
            str(payload.get("status") or ""),
            str(payload.get("resolution") or ""),
            int(payload.get("revision") or 0),
        )
        self.knowledge.capture_decision(
            project_id=project_id,
            title=f"处理 PRD 假设：{assumption['statement'][:120]}",
            selected=assumption["status"],
            reason=assumption["resolution"],
            options=("accepted", "rejected", "replaced"),
            prd_version=version,
        )
        return assumption

    def _assess(
        self,
        project: dict[str, Any],
        *,
        round_id: str,
        round_number: int,
    ) -> tuple[DiscoveryAssessment, dict[str, Any]]:
        context = self.knowledge.context(
            project["idea"],
            target_project_id=project["id"],
            phase="discovery",
            technology_stack=project["baseline"].get("technology_stack") or (),
        )
        previous = self.store.discovery_assessment(project["id"])
        transcript = self.store.discovery_questions(project["id"])
        raw = self.product_model.assess_discovery(
            project["idea"],
            project["baseline"],
            transcript,
            context["rendered"],
            previous,
        )
        assessment = self.readiness.normalize(
            DiscoveryAssessment.from_dict(raw),
            idea=project["idea"],
            baseline=project["baseline"],
            previous_questions=transcript,
        )
        stored = self.store.save_discovery_assessment(
            project["id"], round_id, round_number, assessment.to_dict()
        )
        return replace(
            assessment, policy_blockers=tuple(stored["policy_blockers"])
        ), context

    def _open_next_round(
        self,
        project: dict[str, Any],
        assessment: DiscoveryAssessment,
    ) -> dict[str, Any]:
        questions = [item.to_dict() for item in assessment.next_questions]
        if not questions:
            self.store.update_discovery_session(project["id"], status="checkpoint")
            return {"questions": []}
        return self.store.create_discovery_round(project["id"], questions)

    def _create_prd(
        self,
        project: dict[str, Any],
        assessment: DiscoveryAssessment,
        *,
        force_assumptions: bool,
        change_request: str = "",
        previous_prd: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = self.knowledge.context(
            project["idea"],
            target_project_id=project["id"],
            phase="prd",
            technology_stack=project["baseline"].get("technology_stack") or (),
        )
        transcript = self.store.discovery_questions(project["id"])
        assessment_row = self.store.discovery_assessment(project["id"]) or {}
        assessment_data = assessment.to_dict()
        raw = self.product_model.build_prd(
            project["idea"],
            project["baseline"],
            transcript,
            context["rendered"],
            assessment_data,
            force_assumptions=force_assumptions,
            change_request=change_request,
            previous_prd=previous_prd,
        )
        raw["discovery_assessment_id"] = assessment_row.get("id") or ""
        raw["readiness_snapshot"] = assessment_data
        if force_assumptions:
            forced = [
                {
                    "statement": item,
                    "source": "discovery_policy",
                    "impact": item,
                    "risk": "high",
                }
                for item in assessment.policy_blockers
            ]
            raw["assumptions"] = [*(raw.get("assumptions") or ()), *forced]
            raw["open_questions"] = []
        structural_blockers = raw_prd_structure_blockers(raw)
        document = normalize_prd(
            raw, self.baseline_inspector.inspect(project["workspace_path"])
        )
        validation = self._validate(
            project["id"],
            document,
            assessment,
            structural_blockers=structural_blockers,
        )
        document = replace(
            document,
            validation_summary={
                **validation.to_dict(),
                "structural_blockers": list(structural_blockers),
            },
        )
        status = "review" if validation.passed or force_assumptions else "draft"
        stored = self.store.create_prd(
            project["id"],
            document.to_dict(),
            change_summary=change_request,
            status=status,
        )
        self.store.save_prd_validation(
            project["id"], stored["version"], validation.to_dict()
        )
        assumptions = _merge_assumptions(
            [*assessment.assumptions, *document.assumptions]
        )
        self.store.create_product_assumptions(
            project["id"], stored["version"], assumptions
        )
        if validation.passed or force_assumptions:
            self.store.update_discovery_session(project["id"], status="completed")
            self.store.update_project(
                project["id"],
                state=StudioState.PRD_REVIEW.value,
                definition=document.project_definition.to_dict(),
            )
        else:
            questions = [item.to_dict() for item in validation.follow_up_questions]
            if questions:
                self.store.create_discovery_round(project["id"], questions)
            else:
                self.store.update_discovery_session(project["id"], status="checkpoint")
        return self._result(project["id"], knowledge_context=context)

    def _validate(
        self,
        project_id: str,
        document: PrdDocument,
        assessment: DiscoveryAssessment,
        *,
        structural_blockers: tuple[str, ...] = (),
    ) -> PRDValidation:
        raw = self.product_model.validate_prd(
            document.to_dict(),
            self.store.discovery_questions(project_id),
            assessment.to_dict(),
        )
        model_validation = PRDValidation.from_dict(raw)
        if structural_blockers:
            model_validation = replace(
                model_validation,
                passed=False,
                blockers=tuple(
                    dict.fromkeys((*model_validation.blockers, *structural_blockers))
                ),
            )
        return validate_prd(document, model_validation)

    def _latest_assessment(self, project_id: str) -> DiscoveryAssessment:
        value = self.store.discovery_assessment(project_id)
        if value is None:
            raise Problem(
                "discovery_assessment_missing", "Discovery has not been assessed"
            )
        return DiscoveryAssessment.from_dict(value)

    def _result(
        self,
        project_id: str,
        *,
        knowledge_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            prd = self.store.get_prd(project_id)
        except Problem:
            prd = None
        discovery = self.store.discovery_snapshot(project_id)
        return {
            "project": self.store.get_project(project_id),
            "discovery": discovery,
            "questions": discovery["questions"],
            "prd": prd,
            "prd_validation": self.store.prd_validation(
                project_id, prd["version"] if prd else None
            ),
            "assumptions": self.store.product_assumptions(project_id, prd["version"])
            if prd
            else [],
            "knowledge_context": knowledge_context or {},
        }


def _merge_assumptions(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one review decision per material assumption statement."""
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    merged: dict[str, dict[str, Any]] = {}
    for item in values:
        statement = str(item.get("statement") or item.get("assumption") or "").strip()
        if not statement:
            continue
        key = " ".join(statement.lower().split())[:4000]
        value = dict(item)
        value["statement"] = statement
        current = merged.get(key)
        if current is None:
            merged[key] = value
            continue
        current_risk = str(current.get("risk") or "medium").lower()
        next_risk = str(value.get("risk") or "medium").lower()
        if risk_order.get(next_risk, 1) > risk_order.get(current_risk, 1):
            current["risk"] = next_risk
        for field in ("source", "impact"):
            if not current.get(field) and value.get(field):
                current[field] = value[field]
    return list(merged.values())
