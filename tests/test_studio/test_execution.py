import subprocess

import pytest

from onep.domain import Problem
from onep.runtime.engineering import (
    ExecutionResult,
    RuntimeCapabilities,
    RuntimeProbe,
)
from onep.studio.execution import IndependentVerifier, StudioExecutionService

from .test_product_studio import _service


class FakeCodexRuntime:
    def __init__(self, *, block_first_review=False, unresolved_first=False):
        self.block_first_review = block_first_review
        self.unresolved_first = unresolved_first
        self.execute_calls = 0
        self.review_calls = 0
        self.completed_goals = []
        self.closed = False

    def probe(self):
        return RuntimeProbe(
            "codex_app_server", True, "ready",
            RuntimeCapabilities(
                persistent_sessions=True, structured_output=True,
                streaming=True, goal=True, review=True, approvals=True,
                skills=True, plan=True, user_input=True, detached_review=True,
            ),
            authentication="authenticated", models=("test",),
        )

    def execute(self, request, *, event_sink=None):
        self.execute_calls += 1
        if event_sink and request.strategy in {"plan_then_execute", "plan_then_goal"}:
            event_sink({
                "type": "runtime.plan.finalized",
                "payload": {
                    "threadId": "thread-feature", "turnId": "plan-turn",
                    "plan": [{"step": "实现获批功能", "status": "pending"}],
                },
            })
        target = request.workspace / "delivery.txt"
        target.write_text(f"attempt {self.execute_calls}\n", encoding="utf-8")
        if event_sink:
            event_sink({
                "type": "runtime.turn.completed",
                "payload": {"threadId": "thread-feature", "turnId": f"turn-{self.execute_calls}"},
            })
        return ExecutionResult(
            backend_id="codex_app_server", status="completed",
            final_response="implemented", session_id="thread-feature",
            turn_id=f"turn-{self.execute_calls}", changed_files=("delivery.txt",),
            unresolved_blockers=(
                ("实现仍有未解决问题",)
                if self.unresolved_first and self.execute_calls == 1 else ()
            ),
            plan=({"step": "实现获批功能", "status": "pending"},),
        )

    def review(self, session_id, request, *, event_sink=None):
        self.review_calls += 1
        findings = ()
        if self.block_first_review and self.review_calls == 1:
            findings = ({"priority": "P1", "summary": "缺少边界处理", "blocking": True},)
        return ExecutionResult(
            backend_id="codex_app_server", status="completed",
            final_response="reviewed", session_id="review-thread",
            turn_id=f"review-{self.review_calls}", review_findings=findings,
        )

    def close(self):
        self.closed = True

    def complete_goal(self, session_id):
        self.completed_goals.append(session_id)
        return True


class PassingVerifier:
    def run(self, workspace, configured, timeout=900):
        return [{
            "command": "focused-test", "passed": True, "exit_code": 0,
            "stdout": "ok", "stderr": "", "timed_out": False,
        }]


def _approved_project(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    (repository / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=repository, check=True, capture_output=True,
    )
    service = _service(tmp_path)
    created = service.create_project({"idea": "交付一个功能", "repo": str(repository)})
    reviewed = service.answer_discovery(created["project"]["id"], {"answers": [
        {"question_id": question["id"], "answer": "答案"}
        for question in created["questions"]
    ]})
    approved = service.approve_prd(
        created["project"]["id"], reviewed["prd"]["version"], {"feature_ids": ["F-1"]}
    )
    return service, approved


def test_detached_review_blocker_repairs_on_original_thread_before_delivery(
    tmp_path, monkeypatch,
):
    config_dir = tmp_path / "config"
    monkeypatch.setattr("onep.config._config_dir", lambda: config_dir)
    monkeypatch.setattr("onep.studio.execution._config_dir", lambda: config_dir)
    service, approved = _approved_project(tmp_path)
    runtime = FakeCodexRuntime(block_first_review=True)
    execution = StudioExecutionService(
        service.store,
        runtime_factory=lambda *_args, **_kwargs: runtime,
        verifier=PassingVerifier(),
    )

    result = execution.execute_project(approved["project"]["id"])

    assert result["status"] == "delivered"
    assert runtime.execute_calls == 2
    assert runtime.review_calls == 2
    assert runtime.closed is True
    snapshot = service.studio(approved["project"]["id"])
    assert snapshot["project"]["state"] == "delivered"
    assert snapshot["execution_units"][0]["thread_id"] == "thread-feature"
    assert snapshot["execution_units"][0]["status"] == "completed"
    plan = snapshot["execution_units"][0]["plan"]
    assert plan[0]["execution_unit_id"] == snapshot["execution_units"][0]["id"]
    assert plan[0]["dependencies"] == []
    review_evidence = [item for item in snapshot["evidence"] if item["kind"] == "detached_review"]
    assert [item["passed"] for item in review_evidence] == [False, True]
    assert any(item["kind"] == "integrated_commit" for item in snapshot["evidence"])
    command_evidence = next(
        item for item in snapshot["evidence"] if item["kind"] == "command_result"
    )
    assert "stdout" not in command_evidence["detail"]
    assert command_evidence["detail"]["artifact_ref"]
    artifacts = service.store.artifacts(approved["project"]["id"])
    assert artifacts[0]["id"] == command_evidence["detail"]["artifact_ref"]


def test_runtime_blocker_requires_repair_even_when_tests_pass(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr("onep.config._config_dir", lambda: config_dir)
    monkeypatch.setattr("onep.studio.execution._config_dir", lambda: config_dir)
    service, approved = _approved_project(tmp_path)
    runtime = FakeCodexRuntime(unresolved_first=True)
    execution = StudioExecutionService(
        service.store,
        runtime_factory=lambda *_args, **_kwargs: runtime,
        verifier=PassingVerifier(),
    )

    result = execution.execute_project(approved["project"]["id"])

    assert result["status"] == "delivered"
    assert runtime.execute_calls == 2
    failures = [
        value for value in service.store.knowledge_rows(approved["project"]["id"])
        if value["type"] == "failure"
    ]
    assert any("未解决问题" in value["failure_symptom"] for value in failures)


def test_verifier_rejects_general_purpose_commands(tmp_path):
    verifier = IndependentVerifier()

    with pytest.raises(Problem) as error:
        verifier.run(tmp_path, ["python -c 'print(1)'"])

    assert error.value.code == "unsafe_verification_command"


def test_execution_stops_when_product_contract_changes(tmp_path):
    service, approved = _approved_project(tmp_path)
    execution = StudioExecutionService(service.store)
    project_id = approved["project"]["id"]
    service.store.update_project(project_id, state="prd_review")

    with pytest.raises(Problem) as error:
        execution._assert_project_active(project_id, approved["release"]["id"])

    assert error.value.code == "execution_product_change_pending"
