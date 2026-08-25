import json
from types import SimpleNamespace

import pytest

from onep.runtime.codex_app_server import (
    CodexAppServerRuntime,
    CodexAppServerRuntimeError,
)
from onep.runtime.engineering import ExecutionRequest
from onep.runtime.factory import build_codex_runtime


class FakeAppServerClient:
    def __init__(self, notifications=None):
        self.notifications = list(notifications or ())
        self.requests = []
        self.handler = None
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def set_server_request_handler(self, handler):
        self.handler = handler

    def request(self, method, params, **_kwargs):
        self.requests.append((method, params))
        if method == "account/read":
            return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
        if method == "model/list":
            return {"data": [{"id": "gpt-test"}], "nextCursor": None}
        if method == "collaborationMode/list":
            return {"data": [{"name": "Plan", "mode": "plan"}]}
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            identifier = params.get("threadId") or "thread-1"
            if method == "thread/fork":
                identifier = "thread-review"
            return {"thread": {"id": identifier}}
        if method == "thread/goal/set":
            return {
                "goal": {
                    "threadId": params["threadId"],
                    "objective": params.get("objective") or "goal",
                    "status": params.get("status") or "active",
                    "tokenBudget": params.get("tokenBudget") or 0,
                    "tokensUsed": 3,
                    "timeUsedSeconds": 2,
                }
            }
        if method == "thread/goal/get":
            return {
                "goal": {
                    "threadId": params["threadId"],
                    "objective": "goal",
                    "status": "active",
                }
            }
        if method == "turn/start":
            return {"turn": {"id": "turn-1", "status": "inProgress"}}
        if method == "review/start":
            return {
                "turn": {"id": "review-turn", "status": "inProgress"},
                "reviewThreadId": "thread-review",
            }
        return {}

    def next_notification(self, _timeout):
        if not self.notifications:
            raise AssertionError("runtime requested an unexpected notification")
        return self.notifications.pop(0)

    def close(self):
        self.closed = True


def _config(**overrides):
    values = {
        "codex_model": "gpt-test",
        "codex_provider": "",
        "codex_auth_mode": "existing",
        "codex_api_key_env": "OPENAI_API_KEY",
        "codex_bin": "codex",
        "codex_approval_policy": "never",
        "codex_request_timeout_seconds": 5,
        "codex_app_server_timeout_seconds": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(tmp_path, session_id=""):
    return ExecutionRequest(
        project_id="project",
        run_id="run",
        work_item_id="WI-1",
        attempt=1,
        workspace=tmp_path,
        objective="implement behavior",
        instructions="edit src/app.py and preserve tests",
        contract_id="dc_run",
        contract_version=3,
        baseline_fingerprint="sha256:base",
        acceptance_rule_ids=("AR-1",),
        session_id=session_id,
        max_tokens=4000,
        deadline_seconds=30,
        strategy="goal",
    )


def _notifications():
    summary = json.dumps(
        {
            "schema_version": 1,
            "contract_version": 3,
            "baseline_fingerprint": "sha256:base",
            "changed_files": ["src/app.py"],
            "commands_attempted": ["pytest -q"],
            "unresolved_blockers": [],
            "summary": "implemented",
        }
    )
    return [
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1", "status": "inProgress"}},
        },
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "status": "completed",
                    "aggregatedOutput": "secret output must not enter events",
                }
            },
        },
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "file-1",
                    "type": "fileChange",
                    "status": "completed",
                    "changes": [{"path": "src/app.py", "kind": "update"}],
                }
            },
        },
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "msg-1",
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": summary,
                }
            },
        },
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "tokenUsage": {
                    "last": {"inputTokens": 10, "outputTokens": 5}
                },
            },
        },
        {
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-1", "status": "completed"}},
        },
    ]


def _plain_turn_notifications(turn_id, text):
    return [
        {
            "method": "item/completed",
            "params": {"item": {"id": f"message-{turn_id}", "type": "agentMessage", "text": text}},
        },
        {
            "method": "turn/completed",
            "params": {"turn": {"id": turn_id, "status": "completed"}},
        },
    ]


def test_app_server_runtime_probes_projects_goal_and_executes(tmp_path):
    client = FakeAppServerClient(_notifications())
    events = []
    runtime = CodexAppServerRuntime(_config(), client_factory=lambda: client)

    assert runtime.probe().available is True
    result = runtime.execute(_request(tmp_path), event_sink=events.append)
    goal = runtime.get_goal(result.session_id)
    runtime.complete_goal(result.session_id)
    runtime.archive(result.session_id)
    runtime.close()

    assert result.final_response == "implemented"
    assert result.changed_files == ("src/app.py",)
    assert result.commands_attempted == ("pytest -q",)
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}
    assert goal is not None and goal.status == "active"
    start = next(params for method, params in client.requests if method == "thread/start")
    assert start["sandbox"] == "workspaceWrite"
    assert start["config"] == {
        "sandbox_workspace_write": {"network_access": False}
    }
    turn = next(params for method, params in client.requests if method == "turn/start")
    assert turn["sandboxPolicy"]["networkAccess"] is False
    assert turn["input"][1]["type"] == "skill"
    assert turn["input"][1]["name"] == "onep-delivery"
    assert "edit src/app.py" in turn["input"][0]["text"]
    assert "secret output" not in json.dumps(result.events)
    assert events[-1]["type"] == "runtime.turn.completed"
    assert any(
        method == "thread/goal/set" and params.get("status") == "complete"
        for method, params in client.requests
    )
    assert client.closed is True


def test_app_server_runtime_resumes_persisted_thread(tmp_path):
    client = FakeAppServerClient(_notifications())
    runtime = CodexAppServerRuntime(_config(), client_factory=lambda: client)

    result = runtime.execute(_request(tmp_path, "thread-existing"))

    assert result.session_id == "thread-existing"
    resume = next(
        params for method, params in client.requests if method == "thread/resume"
    )
    assert resume["sandbox"] == "workspaceWrite"
    assert "OnePTeam" in resume["developerInstructions"]
    assert resume["config"] == {
        "sandbox_workspace_write": {"network_access": False}
    }


def test_app_server_runtime_declines_unhandled_runtime_permissions():
    runtime = CodexAppServerRuntime(_config())

    assert runtime._handle_server_request(
        "item/commandExecution/requestApproval", {"reason": "network"}
    ) == {"decision": "decline"}
    assert runtime._handle_server_request(
        "item/permissions/requestApproval", {"reason": "outside workspace"}
    ) == {"permissions": {}, "scope": "turn"}
    assert runtime._handle_server_request(
        "mcpServer/elicitation/request", {"reason": "input requested"}
    ) == {"action": "decline", "content": None, "_meta": None}
    with pytest.raises(CodexAppServerRuntimeError, match="Unsupported server request"):
        runtime._handle_server_request("unknown/request", {})


def test_app_server_runtime_omits_unbounded_goal_budget():
    client = FakeAppServerClient()
    runtime = CodexAppServerRuntime(_config(), client_factory=lambda: client)

    runtime.set_goal("thread-1", "bounded work item")

    params = client.requests[-1][1]
    assert params["status"] == "active"
    assert "tokenBudget" not in params


def test_app_server_runtime_rejects_mismatched_contract_output(tmp_path):
    notifications = _notifications()
    message = next(
        value
        for value in notifications
        if (value.get("params") or {}).get("item", {}).get("type") == "agentMessage"
    )
    parsed = json.loads(message["params"]["item"]["text"])
    parsed["contract_version"] = 99
    message["params"]["item"]["text"] = json.dumps(parsed)
    runtime = CodexAppServerRuntime(
        _config(), client_factory=lambda: FakeAppServerClient(notifications)
    )

    with pytest.raises(CodexAppServerRuntimeError, match="mismatched contract"):
        runtime.execute(_request(tmp_path))


def test_plan_mode_compiles_only_the_final_plan_response(tmp_path):
    request = _request(tmp_path)
    request = ExecutionRequest(
        **{**request.__dict__, "strategy": "plan_then_execute"}
    )
    notifications = [
        {
            "method": "turn/plan/updated",
            "params": {
                "turnId": "turn-1",
                "plan": [{"step": "transient step", "status": "inProgress"}],
            },
        },
        *_plain_turn_notifications("turn-1", "1. Inspect API\n2. Implement schema"),
        *_notifications(),
    ]
    client = FakeAppServerClient(notifications)
    runtime = CodexAppServerRuntime(_config(), client_factory=lambda: client)

    events = []
    result = runtime.execute(request, event_sink=events.append)

    assert result.plan == (
        {"step": "Inspect API", "status": "pending"},
        {"step": "Implement schema", "status": "pending"},
    )
    assert all(value["step"] != "transient step" for value in result.plan)
    finalized = next(value for value in events if value["type"] == "runtime.plan.finalized")
    assert finalized["payload"]["plan"] == list(result.plan)
    turns = [params for method, params in client.requests if method == "turn/start"]
    assert turns[0]["collaborationMode"]["mode"] == "plan"
    assert "collaborationMode" not in turns[1]


def test_detached_review_exposes_blocking_priorities(tmp_path):
    client = FakeAppServerClient(
        _plain_turn_notifications(
            "review-turn", "[P1] Missing authorization check\n[P2] Improve naming"
        )
    )
    runtime = CodexAppServerRuntime(_config(), client_factory=lambda: client)

    result = runtime.review("thread-1", _request(tmp_path))

    assert result.session_id == "thread-review"
    assert [finding["blocking"] for finding in result.review_findings] == [True, False]
    params = next(params for method, params in client.requests if method == "review/start")
    assert params == {
        "threadId": "thread-1",
        "delivery": "detached",
        "target": {"type": "uncommittedChanges"},
    }


def test_factory_selects_app_server_without_changing_backend_contract():
    config = _config()

    runtime = build_codex_runtime(config)

    assert isinstance(runtime, CodexAppServerRuntime)
    assert runtime.backend_id == "codex_app_server"
