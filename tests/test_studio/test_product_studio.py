import pytest

from onep.domain import Problem
from onep.studio.service import StudioService
from onep.studio.store import StudioStore


class FakeProductModel:
    def assess_discovery(
        self,
        idea,
        baseline,
        transcript,
        knowledge_context,
        previous_assessment=None,
    ):
        assert idea
        assert "sanitized" not in knowledge_context.lower()
        answered = bool(transcript) and all(
            question["status"] == "answered" for question in transcript
        )
        coverage = {
            "target_user": "confirmed" if answered else "missing",
            "core_problem": "confirmed",
            "primary_scenario": "confirmed",
            "value_proposition": "confirmed",
            "product_scope": "confirmed",
            "release_boundary": "confirmed",
            "success_metrics": "confirmed" if answered else "missing",
            "constraints": "confirmed",
        }
        return {
            "ready_to_draft": answered,
            "readiness_score": 1.0 if answered else 0.75,
            "coverage": coverage,
            "confirmed_facts": ["用户要求先定义产品再交付"],
            "assumptions": [],
            "open_decisions": [],
            "conflicts": [],
            "risk_flags": [],
            "next_questions": []
            if answered
            else [
                {
                    "dimension": "target_user",
                    "question": "首要用户是谁？",
                    "impact": "决定产品边界",
                    "question_type": "free_text",
                },
                {
                    "dimension": "success_metrics",
                    "question": "首发成功标准？",
                    "impact": "决定验收",
                    "question_type": "free_text",
                },
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
                "target_users": ["独立开发者"],
                "core_problem": idea,
                "scenarios": ["从一句话开始"],
                "value_proposition": "定义后再交付",
                "differentiation": ["知识复用"],
                "principles": ["先审批"],
                "success_metrics": ["验收通过"],
                "non_goals": ["自动发布"],
            },
            "baseline": baseline,
            "summary": "完整产品定义",
            "positioning": "产品与工程闭环",
            "requirements": [{"id": "REQ-1", "description": "形成 PRD"}],
            "features": [
                {
                    "id": "F-1",
                    "title": "产品发现",
                    "product_role": "建立定位",
                    "target_users": ["独立开发者"],
                    "user_outcome": "获得 PRD",
                    "scope": ["问答"],
                    "non_scope": ["发布"],
                    "flows": ["回答问题"],
                    "rules": ["批准前不写代码"],
                    "dependencies": [],
                    "acceptance": ["PRD 可审批"],
                    "metrics": ["问题不超过三个"],
                    "verification_commands": ["python -m pytest -q"],
                    "execution_strategy": "direct",
                    "strategy_reason": "范围局部",
                },
                {
                    "id": "F-2",
                    "title": "跨模块执行",
                    "product_role": "可靠交付",
                    "target_users": ["开发者"],
                    "user_outcome": "获得代码",
                    "scope": ["API", "schema"],
                    "non_scope": [],
                    "flows": ["执行"],
                    "rules": [],
                    "dependencies": ["F-1"],
                    "acceptance": ["质量门通过"],
                    "metrics": [],
                    "verification_commands": [],
                    "execution_strategy": "auto",
                    "strategy_reason": "",
                },
            ],
            "release_feature_ids": ["F-1", "F-2"],
            "risks": ["范围漂移"],
            "assumptions": [],
            "open_questions": [],
            "decision_log": [{"decision": "先审批", "source": "user"}],
            **(
                {"change_impact": {"affected_features": ["F-2"]}}
                if change_request
                else {}
            ),
        }

    def validate_prd(self, prd, transcript, assessment):
        return {
            "passed": True,
            "blockers": [],
            "warnings": [],
            "issues": [],
            "follow_up_questions": [],
        }


def _service(tmp_path):
    return StudioService(
        StudioStore(tmp_path / "studio.db"), product_model=FakeProductModel()
    )


def test_prd_approval_is_a_hard_code_write_gate(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    marker = workspace / "unchanged.txt"
    marker.write_text("before", encoding="utf-8")
    service = _service(tmp_path)

    created = service.create_project(
        {"idea": "把一句话需求变成可靠软件", "repo": str(workspace)},
        action_id="create-1",
    )
    project_id = created["project"]["id"]
    assert marker.read_text(encoding="utf-8") == "before"
    assert len(created["questions"]) == 2

    answers = [
        {"question_id": question["id"], "answer": "明确答案"}
        for question in created["questions"]
    ]
    reviewed = service.answer_discovery(
        project_id, {"answers": answers}, action_id="answer-1"
    )
    assert reviewed["project"]["state"] == "prd_review"
    assert marker.read_text(encoding="utf-8") == "before"

    approved = service.approve_prd(
        project_id,
        reviewed["prd"]["version"],
        {
            "feature_ids": ["F-1", "F-2"],
            "strategy_overrides": {"F-1": "goal"},
        },
        action_id="approve-1",
    )
    assert approved["project"]["state"] == "ready"
    assert [unit["feature_id"] for unit in approved["execution_units"]] == [
        "F-1",
        "F-2",
    ]
    assert approved["execution_units"][0]["strategy"] == "goal"
    assert approved["execution_units"][1]["strategy"] == "plan_then_execute"
    assert marker.read_text(encoding="utf-8") == "before"

    replay = service.approve_prd(
        project_id, reviewed["prd"]["version"], {}, action_id="approve-1"
    )
    assert replay["release"]["id"] == approved["release"]["id"]


def test_product_change_creates_new_prd_and_requires_reapproval(tmp_path):
    service = _service(tmp_path)
    created = service.create_project({"idea": "产品", "repo": str(tmp_path / "repo")})
    project_id = created["project"]["id"]
    reviewed = service.answer_discovery(
        project_id,
        {
            "answers": [
                {"question_id": question["id"], "answer": "答案"}
                for question in created["questions"]
            ]
        },
    )
    service.approve_prd(project_id, reviewed["prd"]["version"], {})

    changed = service.propose_change(project_id, {"request": "增加团队审批"})

    assert changed["prd"]["version"] == reviewed["prd"]["version"] + 1
    assert changed["prd"]["status"] == "review"
    assert service.store.get_project(project_id)["state"] == "prd_review"


def test_execution_rejects_unapproved_release(tmp_path):
    from onep.studio.execution import StudioExecutionService

    service = _service(tmp_path)
    created = service.create_project({"idea": "产品", "repo": str(tmp_path / "repo")})
    with pytest.raises(Problem) as error:
        StudioExecutionService(service.store).execute_project(created["project"]["id"])
    assert error.value.code == "release_not_approved"


def test_pending_interaction_must_be_resolved_before_resume(tmp_path):
    service = _service(tmp_path)
    project = service.store.create_project("项目", "需求", str(tmp_path / "repo"))
    service.store.update_project(project["id"], state="blocked")
    interaction = service.store.create_interaction(
        {
            "project_id": project["id"],
            "kind": "runtime_permission",
            "prompt": "允许修改文件吗？",
            "options": ["accept", "decline"],
        }
    )

    with pytest.raises(Problem) as error:
        service.set_project_state(project["id"], "resume")
    assert error.value.code == "interaction_resolution_required"

    service.resolve_interaction(
        interaction["id"], {"response": "accept", "revision": 1}
    )
    resumed = service.set_project_state(project["id"], "resume")
    assert resumed["state"] == "discovery"
    decisions = [
        value
        for value in service.store.knowledge_rows(project["id"])
        if value["type"] == "decision"
    ]
    assert decisions[0]["selected"] == "accept"
