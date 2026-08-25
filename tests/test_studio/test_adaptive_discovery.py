from pathlib import Path

import pytest

from onep.domain import Problem
from onep.studio.discovery import BASE_DIMENSIONS
from onep.studio.service import StudioService
from onep.studio.store import StudioStore


class AdaptiveProductModel:
    def __init__(self, *, ready_after=2, validation_blocker=False):
        self.ready_after = ready_after
        self.validation_blocker = validation_blocker

    def assess_discovery(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        previous_assessment=None,
    ):
        answered_rounds = len(
            {
                item["round_number"]
                for item in transcript
                if item["status"] == "answered"
            }
        )
        ready = self.ready_after is not None and answered_rounds >= self.ready_after
        dimensions = ("target_user", "product_scope", "success_metrics", "constraints")
        missing = dimensions[min(answered_rounds, len(dimensions) - 1)]
        coverage = {dimension: "confirmed" for dimension in BASE_DIMENSIONS}
        if not ready:
            coverage[missing] = "missing"
        return {
            "ready_to_draft": ready,
            "readiness_score": 1.0 if ready else 0.7,
            "coverage": coverage,
            "confirmed_facts": ["已确认事实"],
            "assumptions": [],
            "open_decisions": [],
            "conflicts": [],
            "risk_flags": [],
            "next_questions": []
            if ready
            else [
                {
                    "dimension": missing,
                    "question": f"第 {answered_rounds + 1} 轮确认 {missing}？",
                    "impact": "会改变产品定义和 Release",
                    "question_type": "free_text",
                    "recommended_answer": f"建议的 {missing}",
                    "recommendation_reason": "基于当前产品目标",
                    "required": True,
                }
            ],
        }

    def build_prd(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        assessment,
        force_assumptions=False,
        change_request="",
        previous_prd=None,
    ):
        return {
            "project_definition": {
                "target_users": ["产品团队"],
                "core_problem": idea,
                "scenarios": ["定义并交付产品"],
                "value_proposition": "先形成正确产品定义",
                "differentiation": ["自适应 Discovery"],
                "principles": ["批准前零代码写入"],
                "success_metrics": ["PRD 无 blocker"],
                "non_goals": ["自动发布"],
            },
            "summary": "自适应产品定义",
            "positioning": "产品定义与交付平台",
            "requirements": [{"id": "REQ-1", "title": "形成完整 PRD"}],
            "features": [
                {
                    "id": "F-1",
                    "title": "多轮 Discovery",
                    "product_role": "形成产品定位",
                    "target_users": ["产品团队"],
                    "user_outcome": "获得完整 PRD",
                    "scope": ["多轮澄清"],
                    "non_scope": ["自动发布"],
                    "flows": ["评估", "提问", "审批"],
                    "rules": ["每轮最多三个问题"],
                    "dependencies": [],
                    "acceptance": ["复杂需求不会提前生成 PRD"],
                    "metrics": ["完整度达到 80%"],
                    "verification_commands": ["python -m pytest -q"],
                }
            ],
            "release_feature_ids": ["F-1"],
            "risks": [],
            "assumptions": [],
            "open_questions": [],
            "decision_log": [],
        }

    def validate_prd(self, prd, transcript, assessment):
        if self.validation_blocker:
            return {
                "passed": False,
                "blockers": ["首版边界仍有冲突"],
                "warnings": [],
                "issues": [],
                "follow_up_questions": [
                    {
                        "dimension": "release_boundary",
                        "question": "请确认首版最终边界",
                        "impact": "解决 PRD blocker",
                        "question_type": "free_text",
                        "required": True,
                    }
                ],
            }
        return {
            "passed": True,
            "blockers": [],
            "warnings": [],
            "issues": [],
            "follow_up_questions": [],
        }


class PrivacyRiskModel(AdaptiveProductModel):
    def assess_discovery(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        previous_assessment=None,
    ):
        coverage = {dimension: "confirmed" for dimension in BASE_DIMENSIONS}
        coverage["data_privacy"] = "missing"
        return {
            "ready_to_draft": True,
            "readiness_score": 1.0,
            "coverage": coverage,
            "confirmed_facts": [],
            "assumptions": [],
            "open_decisions": [],
            "conflicts": [],
            "risk_flags": [],
            "next_questions": [],
        }


class DuplicateAssumptionModel(AdaptiveProductModel):
    def assess_discovery(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        previous_assessment=None,
    ):
        value = super().assess_discovery(
            idea, baseline, transcript, knowledge_context, previous_assessment
        )
        if value["ready_to_draft"]:
            value["assumptions"] = [
                {
                    "statement": "首版只服务产品团队",
                    "source": "model",
                    "impact": "影响首版范围",
                    "risk": "medium",
                }
            ]
        return value

    def build_prd(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        assessment,
        force_assumptions=False,
        change_request="",
        previous_prd=None,
    ):
        value = super().build_prd(
            idea,
            baseline,
            transcript,
            knowledge_context,
            assessment,
            force_assumptions,
            change_request,
            previous_prd,
        )
        value["assumptions"] = [
            {
                "statement": "首版只服务产品团队",
                "source": "model",
                "impact": "影响首版范围",
                "risk": "high",
            }
        ]
        return value


class InvalidStructureModel(AdaptiveProductModel):
    def build_prd(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        assessment,
        force_assumptions=False,
        change_request="",
        previous_prd=None,
    ):
        value = super().build_prd(
            idea,
            baseline,
            transcript,
            knowledge_context,
            assessment,
            force_assumptions,
            change_request,
            previous_prd,
        )
        value["features"].append(dict(value["features"][0]))
        value["release_feature_ids"] = ["F-404"]
        return value


def _service(tmp_path: Path, model) -> StudioService:
    return StudioService(StudioStore(tmp_path / "studio.db"), product_model=model)


def _answer_pending(service: StudioService, project_id: str, action_id: str = ""):
    pending = service.store.discovery_snapshot(project_id)["pending_questions"]
    return service.answer_discovery(
        project_id,
        {
            "answers": [
                {"question_id": question["id"], "answer": "用户确认的答案"}
                for question in pending
            ]
        },
        action_id=action_id,
    )


def test_discovery_uses_multiple_bounded_rounds_before_prd(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    marker = workspace / "unchanged.txt"
    marker.write_text("before", encoding="utf-8")
    service = _service(tmp_path, AdaptiveProductModel(ready_after=2))

    created = service.create_project({"idea": "定义复杂产品", "repo": str(workspace)})
    project_id = created["project"]["id"]
    assert len(created["discovery"]["pending_questions"]) <= 3

    after_round_one = _answer_pending(service, project_id)
    assert after_round_one["prd"] is None
    assert after_round_one["project"]["state"] == "discovery"
    assert after_round_one["discovery"]["session"]["current_round"] == 2

    reviewed = _answer_pending(service, project_id)
    assert reviewed["project"]["state"] == "prd_review"
    assert reviewed["prd"]["status"] == "review"
    assert reviewed["prd_validation"]["passed"] is True
    assert all(
        len(round_value["questions"]) <= 3
        for round_value in reviewed["discovery"]["rounds"]
    )
    assert marker.read_text(encoding="utf-8") == "before"


def test_third_round_creates_checkpoint_and_forced_draft_tracks_assumptions(tmp_path):
    service = _service(tmp_path, AdaptiveProductModel(ready_after=None))
    created = service.create_project({"idea": "仍然模糊的复杂产品"})
    project_id = created["project"]["id"]

    for _ in range(3):
        result = _answer_pending(service, project_id)
    assert result["discovery"]["session"]["status"] == "checkpoint"
    assert result["prd"] is None

    drafted = service.decide_discovery(project_id, {"action": "draft_with_assumptions"})
    assert drafted["project"]["state"] == "prd_review"
    assert drafted["assumptions"]
    assert all(item["risk"] == "high" for item in drafted["assumptions"])
    with pytest.raises(Problem) as error:
        service.approve_prd(project_id, drafted["prd"]["version"], {})
    assert error.value.code == "prd_assumptions_unresolved"

    for assumption in drafted["assumptions"]:
        service.resolve_prd_assumption(
            project_id,
            drafted["prd"]["version"],
            assumption["id"],
            {"status": "accepted", "resolution": "用户确认", "revision": 1},
        )
    approved = service.approve_prd(project_id, drafted["prd"]["version"], {})
    assert approved["project"]["state"] == "ready"


def test_model_readiness_cannot_skip_privacy_risk_dimension(tmp_path):
    service = _service(tmp_path, PrivacyRiskModel())
    created = service.create_project({"idea": "处理用户隐私数据的协作产品"})

    assert created["prd"] is None
    assert created["project"]["state"] == "discovery"
    assert created["discovery"]["pending_questions"][0]["dimension"] == "data_privacy"
    assert "数据与隐私：未确认" in created["discovery"]["assessment"]["policy_blockers"]


def test_prd_validation_blocker_returns_to_discovery(tmp_path):
    service = _service(
        tmp_path, AdaptiveProductModel(ready_after=1, validation_blocker=True)
    )
    created = service.create_project({"idea": "需要独立验证的产品"})
    result = _answer_pending(service, created["project"]["id"])

    assert result["project"]["state"] == "discovery"
    assert result["prd"]["status"] == "draft"
    assert result["prd_validation"]["passed"] is False
    assert (
        result["discovery"]["pending_questions"][0]["dimension"] == "release_boundary"
    )


def test_answer_action_id_does_not_duplicate_next_round(tmp_path):
    service = _service(tmp_path, AdaptiveProductModel(ready_after=2))
    created = service.create_project({"idea": "幂等多轮产品"})
    project_id = created["project"]["id"]
    answers = {
        "answers": [
            {"question_id": question["id"], "answer": "确认"}
            for question in created["discovery"]["pending_questions"]
        ]
    }

    first = service.answer_discovery(project_id, answers, action_id="round-one")
    replay = service.answer_discovery(project_id, answers, action_id="round-one")

    assert first["discovery"]["session"]["current_round"] == 2
    assert replay["discovery"]["session"]["current_round"] == 2
    assert len(service.store.discovery_rounds(project_id)) == 2


def test_checkpoint_decision_cannot_skip_an_active_round(tmp_path):
    service = _service(tmp_path, AdaptiveProductModel(ready_after=2))
    created = service.create_project({"idea": "不能跳过当前问题"})

    with pytest.raises(Problem) as error:
        service.decide_discovery(
            created["project"]["id"], {"action": "draft_with_assumptions"}
        )

    assert error.value.code == "discovery_decision_not_available"


def test_base_dimension_cannot_be_marked_not_applicable(tmp_path):
    class NotApplicableModel(PrivacyRiskModel):
        def assess_discovery(
            self,
            idea,
            baseline,
            transcript,
            knowledge_context,
            previous_assessment=None,
        ):
            value = super().assess_discovery(
                idea, baseline, transcript, knowledge_context, previous_assessment
            )
            value["coverage"]["success_metrics"] = "not_applicable"
            return value

    service = _service(tmp_path, NotApplicableModel())
    created = service.create_project({"idea": "处理用户隐私数据的产品"})

    blockers = created["discovery"]["assessment"]["policy_blockers"]
    assert "成功指标：不适用" in blockers
    assert any(
        question["dimension"] == "success_metrics"
        for question in created["discovery"]["pending_questions"]
    )


def test_duplicate_assumptions_are_merged_at_highest_risk(tmp_path):
    service = _service(tmp_path, DuplicateAssumptionModel(ready_after=1))
    created = service.create_project({"idea": "需要记录产品假设"})
    reviewed = _answer_pending(service, created["project"]["id"])

    assert len(reviewed["assumptions"]) == 1
    assert reviewed["assumptions"][0]["risk"] == "high"


def test_raw_prd_structure_errors_survive_normalization_and_revalidation(tmp_path):
    service = _service(tmp_path, InvalidStructureModel(ready_after=1))
    created = service.create_project({"idea": "不能静默修正错误 PRD"})
    result = _answer_pending(service, created["project"]["id"])

    assert result["prd"]["status"] == "draft"
    assert result["prd_validation"]["passed"] is False
    assert any(
        "重复的 Feature ID" in blocker
        for blocker in result["prd_validation"]["blockers"]
    )
    assert any("F-404" in blocker for blocker in result["prd_validation"]["blockers"])

    validation = service.revalidate_prd(
        created["project"]["id"], result["prd"]["version"]
    )
    assert validation["passed"] is False
    assert any("重复的 Feature ID" in item for item in validation["blockers"])
