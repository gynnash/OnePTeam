"""Official Codex app-server v2 transport for deep OnePTeam integration."""

from __future__ import annotations

import os
from pathlib import Path
import re
import time
from typing import Any, Callable

from onep.runtime.app_server_client import (
    AppServerClient,
    AppServerNotificationTimeout,
    AppServerProtocolError,
)
from onep.runtime.codex_contract import (
    OUTPUT_SCHEMA,
    delivery_skill_path,
    developer_instructions,
    execution_prompt,
    goal_objective,
    parse_structured_response,
    validate_structured_response,
)
from onep.runtime.engineering import (
    ExecutionRequest,
    ExecutionResult,
    RuntimeCapabilities,
    RuntimeEventSink,
    RuntimeGoal,
    RuntimeProbe,
)


class CodexAppServerRuntimeError(RuntimeError):
    pass


class CodexAppServerRuntime:
    backend_id = "codex_app_server"

    def __init__(
        self,
        config,
        *,
        client_factory: Callable[[], Any] | None = None,
        interaction_handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.config = config
        self._client_factory = client_factory
        self._client: Any | None = None
        self._active_turns: dict[str, str] = {}
        self._threads: set[str] = set()
        self._event_sink: RuntimeEventSink | None = None
        self._interaction_handler = interaction_handler

    @property
    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            persistent_sessions=True,
            structured_output=True,
            streaming=True,
            interrupt=True,
            steer=True,
            compact=True,
            fork=True,
            review=True,
            archive=True,
            goal=True,
            approvals=True,
            skills=True,
            plan=True,
            user_input=True,
            detached_review=True,
        )

    def probe(self) -> RuntimeProbe:
        try:
            client = self._ensure_client()
            self._login_api_key_if_requested(client)
            account = client.request("account/read", {"refreshToken": False})
            models_response = client.request(
                "model/list", {"limit": 100, "includeHidden": True}
            )
            modes_response = client.request("collaborationMode/list", {})
        except Exception as exc:
            return RuntimeProbe(
                self.backend_id,
                False,
                f"Codex app-server is not ready: {exc}",
                self.capabilities,
                authentication="required",
            )
        authentication = self._authentication(account)
        models = tuple(self._model_ids(models_response))
        selected_model = str(self.config.codex_model or "").strip()
        model_available = bool(selected_model and selected_model in models)
        plan_available = any(
            str(value.get("mode") or "").lower() == "plan"
            for value in modes_response.get("data") or ()
            if isinstance(value, dict)
        )
        available = (
            authentication == "authenticated" and model_available and plan_available
        )
        if authentication != "authenticated":
            detail = "Run Codex login, or configure an API-key environment variable"
        elif not model_available:
            detail = f"Configured Codex model is not available: {selected_model}"
        elif not plan_available:
            detail = "Codex App Server does not expose the required Plan collaboration mode"
        else:
            detail = (
                "Codex App Server, Plan, Goal, detached Review, Skills, structured "
                "output, streaming, and interactive requests are ready"
            )
        return RuntimeProbe(
            self.backend_id,
            available,
            detail,
            self.capabilities,
            authentication=authentication,
            models=models,
        )

    def start_session(self, request: ExecutionRequest) -> str:
        client = self._ensure_client()
        self._login_api_key_if_requested(client)
        result = client.request("thread/start", self._thread_params(request))
        session_id = self._thread_id(result)
        self._threads.add(session_id)
        self._set_thread_name(session_id, request)
        return session_id

    def resume_session(self, session_id: str, request: ExecutionRequest) -> str:
        result = self._ensure_client().request(
            "thread/resume",
            {
                "threadId": session_id,
                **self._thread_overrides(request),
                "developerInstructions": developer_instructions(),
                "config": {
                    "sandbox_workspace_write": {"network_access": False}
                },
            },
        )
        resumed = self._thread_id(result)
        self._threads.add(resumed)
        return resumed

    def execute(
        self,
        request: ExecutionRequest,
        *,
        event_sink: RuntimeEventSink | None = None,
    ) -> ExecutionResult:
        self._event_sink = event_sink
        client = self._ensure_client()
        client.set_server_request_handler(self._handle_server_request)
        session_id = request.session_id
        try:
            if session_id and session_id in self._threads:
                pass
            elif session_id:
                session_id = self.resume_session(session_id, request)
            else:
                session_id = self.start_session(request)
            strategy = request.strategy or "direct"
            plan: tuple[dict[str, Any], ...] = ()
            if strategy in {"plan_then_execute", "plan_then_goal"}:
                plan_result = self._start_and_wait_turn(
                    client,
                    request,
                    session_id,
                    inputs=[{
                        "type": "text",
                        "text": self._plan_prompt(request),
                    }],
                    collaboration_mode=self._plan_collaboration_mode(request),
                    expect_structured=False,
                )
                plan = plan_result.plan
                if self._event_sink:
                    self._event_sink({
                        "type": "runtime.plan.finalized",
                        "payload": {
                            "threadId": session_id,
                            "turnId": plan_result.turn_id,
                            "plan": list(plan),
                        },
                    })
            if strategy in {"goal", "plan_then_goal"}:
                self.set_goal(session_id, goal_objective(request), request.max_tokens)
            inputs = [
                {
                    "type": "text",
                    "text": execution_prompt(request, invoke_skill=True),
                },
                {
                    "type": "skill",
                    "name": "onep-delivery",
                    "path": str(delivery_skill_path()),
                },
            ]
            result = self._start_and_wait_turn(
                client, request, session_id, inputs=inputs,
                expect_structured=True,
            )
            result = ExecutionResult(**{**result.__dict__, "plan": plan})
        except (AppServerProtocolError, ValueError) as exc:
            raise CodexAppServerRuntimeError(
                f"Codex app-server execution failed: {exc}"
            ) from exc
        finally:
            self._active_turns.pop(session_id, None)
            self._event_sink = None
        return result

    def review(
        self,
        session_id: str,
        request: ExecutionRequest,
        *,
        event_sink: RuntimeEventSink | None = None,
    ) -> ExecutionResult:
        """Run mandatory detached review without granting it write authority."""
        self._event_sink = event_sink
        client = self._ensure_client()
        client.set_server_request_handler(self._handle_server_request)
        response = client.request(
            "review/start",
            {
                "threadId": session_id,
                "delivery": "detached",
                "target": {"type": "uncommittedChanges"},
            },
        )
        turn = response.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        review_thread_id = str(response.get("reviewThreadId") or "")
        if not turn_id or not review_thread_id:
            raise CodexAppServerRuntimeError("Codex detached review did not start")
        self._threads.add(review_thread_id)
        self._active_turns[review_thread_id] = turn_id
        try:
            result = self._wait_for_turn(
                client, request, review_thread_id, turn_id,
                expect_structured=False,
            )
            findings = self._review_findings(result.final_response)
            return ExecutionResult(
                **{**result.__dict__, "review_findings": tuple(findings)}
            )
        finally:
            self._active_turns.pop(review_thread_id, None)
            self._event_sink = None

    def _start_and_wait_turn(
        self,
        client,
        request: ExecutionRequest,
        session_id: str,
        *,
        inputs: list[dict[str, Any]],
        collaboration_mode: dict[str, Any] | None = None,
        expect_structured: bool,
    ) -> ExecutionResult:
        params: dict[str, Any] = {
            "threadId": session_id,
            "input": inputs,
            "cwd": str(request.workspace),
            "approvalPolicy": self.config.codex_approval_policy,
            "sandboxPolicy": self._sandbox_policy(request.workspace),
            "model": request.model or self.config.codex_model or None,
        }
        if expect_structured:
            params["outputSchema"] = OUTPUT_SCHEMA
        if collaboration_mode is not None:
            params["collaborationMode"] = collaboration_mode
        response = client.request("turn/start", params)
        turn = response.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise CodexAppServerRuntimeError("Codex app-server did not return a turn id")
        self._active_turns[session_id] = turn_id
        return self._wait_for_turn(
            client, request, session_id, turn_id,
            expect_structured=expect_structured,
        )

    def interrupt(self, session_id: str) -> bool:
        turn_id = self._active_turns.get(session_id)
        if not turn_id:
            return False
        self._ensure_client().request(
            "turn/interrupt", {"threadId": session_id, "turnId": turn_id}
        )
        return True

    def steer(self, session_id: str, instruction: str) -> bool:
        turn_id = self._active_turns.get(session_id)
        if not turn_id or not instruction.strip():
            return False
        self._ensure_client().request(
            "turn/steer",
            {
                "threadId": session_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": instruction.strip()}],
            },
        )
        return True

    def compact(self, session_id: str) -> bool:
        self._ensure_client().request(
            "thread/compact/start", {"threadId": session_id}
        )
        return True

    def fork(self, session_id: str, request: ExecutionRequest) -> str:
        result = self._ensure_client().request(
            "thread/fork",
            {
                "threadId": session_id,
                "ephemeral": True,
                "cwd": str(request.workspace),
                "sandbox": "readOnly",
                "developerInstructions": developer_instructions(),
                "config": {
                    "sandbox_workspace_write": {"network_access": False}
                },
            },
        )
        forked = self._thread_id(result)
        self._threads.add(forked)
        return forked

    def archive(self, session_id: str) -> bool:
        self._ensure_client().request("thread/archive", {"threadId": session_id})
        self._threads.discard(session_id)
        return True

    def set_goal(
        self, session_id: str, objective: str, token_budget: int = 0
    ) -> RuntimeGoal:
        params: dict[str, Any] = {
            "threadId": session_id,
            "objective": objective[:4000],
            "status": "active",
        }
        if token_budget > 0:
            params["tokenBudget"] = token_budget
        result = self._ensure_client().request("thread/goal/set", params)
        return RuntimeGoal.from_dict(result.get("goal") or {})

    def get_goal(self, session_id: str) -> RuntimeGoal | None:
        result = self._ensure_client().request(
            "thread/goal/get", {"threadId": session_id}
        )
        value = result.get("goal")
        return RuntimeGoal.from_dict(value) if isinstance(value, dict) else None

    def complete_goal(self, session_id: str) -> bool:
        self._ensure_client().request(
            "thread/goal/set", {"threadId": session_id, "status": "complete"}
        )
        return True

    def clear_goal(self, session_id: str) -> bool:
        self._ensure_client().request(
            "thread/goal/clear", {"threadId": session_id}
        )
        return True

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._active_turns.clear()
        self._threads.clear()

    def _ensure_client(self):
        if self._client is None:
            self._client = (
                self._client_factory()
                if self._client_factory is not None
                else AppServerClient(
                    self.config.codex_bin,
                    request_timeout_seconds=self.config.codex_request_timeout_seconds,
                    server_request_handler=self._handle_server_request,
                )
            )
            self._client.start()
        return self._client

    def _login_api_key_if_requested(self, client) -> None:
        if self.config.codex_auth_mode != "api_key":
            return
        value = os.environ.get(self.config.codex_api_key_env, "")
        if not value:
            raise CodexAppServerRuntimeError(
                f"{self.config.codex_api_key_env} is required for Codex API-key auth"
            )
        client.request(
            "account/login/start", {"type": "apiKey", "apiKey": value}
        )

    def _wait_for_turn(
        self,
        client,
        request: ExecutionRequest,
        session_id: str,
        turn_id: str,
        *,
        expect_structured: bool,
    ) -> ExecutionResult:
        deadline_seconds = min(
            request.deadline_seconds,
            self.config.codex_app_server_timeout_seconds,
        )
        deadline = time.monotonic() + max(1, deadline_seconds)
        events: list[dict[str, Any]] = []
        final_text = ""
        changed_files: list[str] = []
        commands: list[str] = []
        usage: dict[str, int] = {}
        status = "failed"
        error_detail = ""
        authoritative_plan = ""
        progress_plan: list[dict[str, Any]] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.interrupt(session_id)
                raise CodexAppServerRuntimeError("Codex app-server turn timed out")
            try:
                message = client.next_notification(min(remaining, 30))
            except AppServerNotificationTimeout:
                continue
            method = str(message.get("method") or "")
            params = message.get("params")
            params = params if isinstance(params, dict) else {}
            mapped = self._event(method, params)
            if mapped:
                events.append(mapped)
                if len(events) > 500:
                    events.pop(0)
                if self._event_sink:
                    self._event_sink(mapped)
            if method == "item/completed":
                item = params.get("item") or {}
                item_type = item.get("type")
                if item_type == "agentMessage" and item.get("text"):
                    final_text = str(item["text"])
                elif item_type == "plan" and item.get("text"):
                    authoritative_plan = str(item["text"])
                elif item_type == "commandExecution" and item.get("command"):
                    commands.append(str(item["command"]))
                elif item_type == "fileChange":
                    changed_files.extend(
                        str(change.get("path"))
                        for change in item.get("changes") or ()
                        if isinstance(change, dict) and change.get("path")
                    )
            elif method == "thread/tokenUsage/updated":
                usage = self._usage(params)
            elif method == "turn/plan/updated":
                progress_plan = [
                    {
                        "step": str(value.get("step") or ""),
                        "status": str(value.get("status") or "pending"),
                    }
                    for value in params.get("plan") or ()
                    if isinstance(value, dict) and value.get("step")
                ]
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if str(turn.get("id") or "") != turn_id:
                    continue
                status = str(turn.get("status") or "failed")
                error = turn.get("error") or {}
                error_detail = str(error.get("message") or "")
                break
        if status != "completed":
            raise CodexAppServerRuntimeError(
                f"Codex app-server turn did not complete: {error_detail or status}"
            )
        if expect_structured:
            parsed = parse_structured_response(final_text)
            validate_structured_response(parsed, request)
        else:
            parsed = {
                "summary": final_text or authoritative_plan,
                "changed_files": [], "commands_attempted": [],
                "unresolved_blockers": [],
            }
        # Plan progress events are transient. Only the final Plan response is compiled.
        plan = self._authoritative_plan(authoritative_plan or final_text, progress_plan)
        return ExecutionResult(
            backend_id=self.backend_id,
            status=status,
            final_response=str(parsed["summary"]),
            session_id=session_id,
            turn_id=turn_id,
            changed_files=tuple(
                dict.fromkeys(
                    [*changed_files, *(str(v) for v in parsed["changed_files"])]
                )
            ),
            commands_attempted=tuple(
                dict.fromkeys([*commands, *(str(v) for v in parsed["commands_attempted"])])
            ),
            unresolved_blockers=tuple(
                str(value) for value in parsed["unresolved_blockers"]
            ),
            usage=usage,
            events=tuple(events),
            termination_reason=(
                "completed" if not parsed["unresolved_blockers"] else "blocked"
            ),
            plan=tuple(plan),
        )

    def _handle_server_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        event = {
            "type": "runtime.permission.requested",
            "payload": {
                "backend_id": self.backend_id,
                "kind": method,
                "thread_id": params.get("threadId"),
                "turn_id": params.get("turnId"),
                "reason": params.get("reason"),
                "decision": "decline",
            },
        }
        if self._event_sink:
            self._event_sink(event)
        if self._interaction_handler is not None:
            return self._interaction_handler(method, params)
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            return {"decision": "decline"}
        if method == "item/permissions/requestApproval":
            return {"permissions": {}, "scope": "turn"}
        if method == "mcpServer/elicitation/request":
            return {"action": "decline", "content": None, "_meta": None}
        raise CodexAppServerRuntimeError(f"Unsupported server request: {method}")

    def _plan_collaboration_mode(self, request: ExecutionRequest) -> dict[str, Any]:
        return {
            "mode": "plan",
            "settings": {
                "model": request.model or self.config.codex_model,
                "reasoning_effort": None,
                "developer_instructions": None,
            },
        }

    @staticmethod
    def _plan_prompt(request: ExecutionRequest) -> str:
        return (
            "Plan this approved OnePTeam feature before implementation. Do not edit files. "
            "The final Plan item is authoritative. Make each step bounded, dependency-aware, "
            "and traceable to acceptance criteria.\n\n"
            f"Objective: {request.objective}\n"
            f"Acceptance: {list(request.acceptance_rule_ids)}\n"
            f"Constraints: {list(request.constraints)}\n"
            "Sanitized prior knowledge (verify before use):\n"
            f"{request.sanitized_knowledge_context[:6000]}"
        )

    @staticmethod
    def _authoritative_plan(
        text: str, progress: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        steps = []
        for line in text.splitlines():
            value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            if value and (
                value != line.strip() or line.strip().startswith(("-", "*"))
            ):
                steps.append({"step": value[:500], "status": "pending"})
        if not steps:
            steps = [{"step": text.strip()[:500], "status": "pending"}]
        return steps[:50]

    @staticmethod
    def _review_findings(text: str) -> list[dict[str, Any]]:
        findings = []
        pattern = re.compile(r"\[(P[0-3])\]\s*([^\n]+)", re.I)
        for match in pattern.finditer(text or ""):
            findings.append(
                {
                    "priority": match.group(1).upper(),
                    "summary": match.group(2).strip(),
                    "blocking": match.group(1).upper() in {"P0", "P1"},
                }
            )
        return findings

    def _thread_params(self, request: ExecutionRequest) -> dict[str, Any]:
        return {
            **self._thread_overrides(request),
            "serviceName": "onepteam",
            "developerInstructions": developer_instructions(),
            "config": {"sandbox_workspace_write": {"network_access": False}},
        }

    def _thread_overrides(self, request: ExecutionRequest) -> dict[str, Any]:
        values: dict[str, Any] = {
            "model": request.model or self.config.codex_model or None,
            "modelProvider": request.model_provider
            or self.config.codex_provider
            or None,
            "cwd": str(request.workspace),
            "approvalPolicy": self.config.codex_approval_policy,
            "sandbox": "workspaceWrite",
        }
        return {key: value for key, value in values.items() if value is not None}

    @staticmethod
    def _sandbox_policy(workspace: Path) -> dict[str, Any]:
        return {
            "type": "workspaceWrite",
            "writableRoots": [str(workspace)],
            "networkAccess": False,
        }

    def _set_thread_name(self, session_id: str, request: ExecutionRequest) -> None:
        try:
            self._ensure_client().request(
                "thread/name/set",
                {
                    "threadId": session_id,
                    "name": f"OnePTeam {request.run_id} / {request.work_item_id}",
                },
            )
        except AppServerProtocolError:
            return

    @staticmethod
    def _thread_id(result: dict[str, Any]) -> str:
        thread = result.get("thread") or {}
        value = str(thread.get("id") or "")
        if not value:
            raise CodexAppServerRuntimeError(
                "Codex app-server did not return a thread id"
            )
        return value

    @staticmethod
    def _authentication(result: dict[str, Any]) -> str:
        if result.get("account") is not None or result.get("requiresOpenaiAuth") is False:
            return "authenticated"
        return "required"

    @staticmethod
    def _model_ids(result: dict[str, Any]) -> list[str]:
        values = result.get("data") or ()
        return [
            str(value.get("id") or value.get("model"))
            for value in values
            if isinstance(value, dict) and (value.get("id") or value.get("model"))
        ]

    @staticmethod
    def _usage(params: dict[str, Any]) -> dict[str, int]:
        source = params.get("tokenUsage") or params.get("usage") or params
        if isinstance(source, dict) and isinstance(source.get("last"), dict):
            source = source["last"]
        if not isinstance(source, dict):
            return {}
        aliases = {
            "inputTokens": "input_tokens",
            "outputTokens": "output_tokens",
            "totalTokens": "total_tokens",
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "total_tokens": "total_tokens",
        }
        return {
            aliases[key]: int(value)
            for key, value in source.items()
            if key in aliases and isinstance(value, (int, float))
        }

    @staticmethod
    def _event(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not method:
            return None
        mapped = {
            "turn/started": "runtime.turn.started",
            "turn/completed": "runtime.turn.completed",
            "turn/plan/updated": "runtime.plan.updated",
            "turn/diff/updated": "runtime.diff.updated",
            "item/started": "runtime.item.started",
            "item/completed": "runtime.item.completed",
            "thread/tokenUsage/updated": "runtime.usage.updated",
            "thread/goal/updated": "runtime.goal.updated",
            "thread/goal/cleared": "runtime.goal.cleared",
            "warning": "runtime.warning",
            "error": "runtime.failed",
        }.get(method, "runtime.event")
        return {
            "type": mapped,
            "payload": CodexAppServerRuntime._safe_event_payload(method, params),
        }

    @staticmethod
    def _safe_event_payload(method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {"method": method}
        for key in ("threadId", "turnId"):
            if params.get(key):
                payload[key] = str(params[key])
        if method.startswith("turn/"):
            turn = params.get("turn") or {}
            payload.update(
                {
                    "turnId": str(turn.get("id") or payload.get("turnId") or ""),
                    "status": str(turn.get("status") or ""),
                }
            )
            error = turn.get("error") or {}
            if error.get("message"):
                payload["error"] = str(error["message"])[:1000]
        elif method.startswith("item/"):
            item = params.get("item") or {}
            payload.update(
                {
                    "itemId": str(item.get("id") or ""),
                    "itemType": str(item.get("type") or ""),
                    "status": str(item.get("status") or ""),
                }
            )
            if item.get("type") == "commandExecution":
                payload["command"] = str(item.get("command") or "")[:1000]
                payload["exitCode"] = item.get("exitCode")
            elif item.get("type") == "fileChange":
                payload["paths"] = [
                    str(change.get("path"))
                    for change in item.get("changes") or ()
                    if isinstance(change, dict) and change.get("path")
                ][:100]
        elif method == "thread/tokenUsage/updated":
            payload["usage"] = CodexAppServerRuntime._usage(params)
        elif method.startswith("thread/goal/"):
            goal = params.get("goal") or {}
            payload.update(
                {
                    "status": str(goal.get("status") or ""),
                    "tokenBudget": int(goal.get("tokenBudget") or 0),
                    "tokensUsed": int(goal.get("tokensUsed") or 0),
                }
            )
        elif params.get("message"):
            payload["message"] = str(params["message"])[:1000]
        return payload
