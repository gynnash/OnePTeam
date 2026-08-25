"""Codex-only execution supervisor with independent gates and knowledge capture."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
from typing import Any, Callable

from onep.config import _config_dir, load_config
from onep.delivery.fingerprint import fingerprint_tree
from onep.domain import Problem
from onep.runtime.codex_app_server import CodexAppServerRuntime
from onep.runtime.engineering import ExecutionRequest
from onep.studio.knowledge import KnowledgeService
from onep.studio.models import StudioState
from onep.studio.privacy import sanitize_for_model
from onep.studio.store import StudioStore


class GitWorktreeManager:
    """Creates persistent release/unit worktrees without touching the user's branch."""

    def __init__(self, source: str | Path, project_id: str, release_id: str) -> None:
        self.source = Path(source).expanduser().resolve()
        self.project_id = project_id
        self.release_id = release_id
        safe_project = re.sub(r"[^a-zA-Z0-9_-]+", "-", project_id)[:40]
        safe_release = re.sub(r"[^a-zA-Z0-9_-]+", "-", release_id)[:40]
        self.root = _config_dir() / "studio-worktrees" / safe_project / safe_release
        self.integration_path = self.root / "integration"
        self.integration_branch = f"onep/{safe_project}/{safe_release}"

    def prepare(self) -> Path:
        self._ensure_repository()
        dirty = self._git(self.source, "status", "--porcelain").stdout.strip()
        if dirty:
            raise Problem(
                "git_worktree_dirty", "Target repository has uncommitted changes",
                dirty[:4000], actionable=True,
                suggested_actions=("commit_or_stash", "retry"),
            )
        self.root.mkdir(parents=True, exist_ok=True)
        if self._is_worktree(self.integration_path):
            return self.integration_path
        branch_exists = self._git(
            self.source, "show-ref", "--verify", "--quiet",
            f"refs/heads/{self.integration_branch}", check=False,
        ).returncode == 0
        args = ["worktree", "add"]
        if not branch_exists:
            args.extend(("-b", self.integration_branch))
        args.extend((str(self.integration_path), self.integration_branch if branch_exists else "HEAD"))
        self._git(self.source, *args)
        return self.integration_path

    def unit_worktree(self, unit_id: str) -> tuple[Path, str]:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", unit_id)[:48]
        path = self.root / safe
        # A Git ref cannot be both a branch and the parent directory of another
        # branch. Use a sibling name instead of `<integration>/<unit>`.
        branch = f"{self.integration_branch}--{safe}"
        if self._is_worktree(path):
            return path, branch
        branch_exists = self._git(
            self.source, "show-ref", "--verify", "--quiet",
            f"refs/heads/{branch}", check=False,
        ).returncode == 0
        args = ["worktree", "add"]
        if not branch_exists:
            args.extend(("-b", branch))
        args.extend((str(path), branch if branch_exists else self.integration_branch))
        self._git(self.source, *args)
        return path, branch

    def commit_and_integrate(self, unit_path: Path, title: str) -> str:
        self._git(unit_path, "add", "-A")
        if not self._git(unit_path, "status", "--porcelain").stdout.strip():
            raise Problem("empty_candidate", "Codex produced no repository changes")
        self._git(
            unit_path, "-c", "user.name=OnePTeam", "-c",
            "user.email=onepteam@local", "commit", "-m", f"feat: {title}",
        )
        commit = self._git(unit_path, "rev-parse", "HEAD").stdout.strip()
        already = self._git(
            self.integration_path, "merge-base", "--is-ancestor", commit, "HEAD",
            check=False,
        ).returncode == 0
        if not already:
            self._git(self.integration_path, "cherry-pick", commit)
        return commit

    def diff_summary(self, unit_path: Path) -> dict[str, Any]:
        """Compute candidate changes independently from Codex self-reporting."""
        diff = self._git(
            unit_path, "diff", "--name-status", self.integration_branch, "--",
            check=False,
        ).stdout.splitlines()
        status = self._git(
            unit_path, "status", "--porcelain=v1", "--untracked-files=all",
            check=False,
        ).stdout.splitlines()
        return {
            "name_status": diff[:500],
            "worktree_status": status[:500],
            "truncated": len(diff) > 500 or len(status) > 500,
        }

    def _ensure_repository(self) -> None:
        if not self.source.exists():
            self.source.mkdir(parents=True)
        if not self.source.is_dir():
            raise Problem("workspace_not_directory", "Workspace is not a directory", str(self.source))
        if self._git(self.source, "rev-parse", "--git-dir", check=False).returncode != 0:
            self._git(self.source, "init")
            self._git(
                self.source, "-c", "user.name=OnePTeam", "-c",
                "user.email=onepteam@local", "commit", "--allow-empty", "-m",
                "chore: initialize OnePTeam workspace",
            )

    @staticmethod
    def _is_worktree(path: Path) -> bool:
        return path.is_dir() and subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        ).returncode == 0

    @staticmethod
    def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        process = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
        )
        if check and process.returncode:
            raise Problem(
                "git_operation_failed", "Git operation failed",
                process.stderr.strip() or " ".join(args),
            )
        return process


class IndependentVerifier:
    SAFE_ACTIONS = {
        "npm": {"test", "build", "lint", "typecheck", "check"},
        "pnpm": {"test", "build", "lint", "typecheck", "check"},
        "yarn": {"test", "build", "lint", "typecheck", "check"},
        "cargo": {"test", "check", "clippy", "fmt"},
        "go": {"test", "vet"},
        "flutter": {"test", "analyze", "build"},
        "dart": {"test", "analyze"},
        "make": {"test", "check", "lint", "build"},
        "just": {"test", "check", "lint", "fmt", "build"},
    }

    def commands(self, workspace: Path, configured: list[str]) -> list[str]:
        commands = list(dict.fromkeys(command.strip() for command in configured if command.strip()))
        if commands:
            return commands
        if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists():
            return ["python -m pytest -q"]
        if (workspace / "package.json").exists():
            try:
                package = json.loads((workspace / "package.json").read_text())
            except (OSError, json.JSONDecodeError):
                package = {}
            if "test" in (package.get("scripts") or {}):
                return ["npm test -- --run"]
        if (workspace / "Cargo.toml").exists():
            return ["cargo test"]
        if (workspace / "go.mod").exists():
            return ["go test ./..."]
        if (workspace / "pubspec.yaml").exists():
            return ["flutter test"]
        return []

    def run(self, workspace: Path, configured: list[str], timeout: int = 900) -> list[dict[str, Any]]:
        results = []
        commands = self.commands(workspace, configured)
        if not commands:
            return [{
                "command": "", "gate_stage": "full", "passed": False,
                "exit_code": 2, "stdout": "",
                "stderr": "No deterministic verification command was discovered.",
                "timed_out": False,
            }]
        for index, command in enumerate(commands):
            argv = shlex.split(command)
            if not self._is_safe_command(argv):
                raise Problem(
                    "unsafe_verification_command", "Verification command is not allowed",
                    command,
                )
            try:
                process = subprocess.run(
                    argv, cwd=workspace, capture_output=True, text=True,
                    timeout=max(1, timeout),
                )
                results.append(
                    {
                        "command": command,
                        "gate_stage": (
                            "full" if index == len(commands) - 1
                            else "focused" if index == 0 else "scoped"
                        ),
                        "passed": process.returncode == 0,
                        "exit_code": process.returncode,
                        "stdout": process.stdout[-12000:], "stderr": process.stderr[-12000:],
                        "timed_out": False,
                    }
                )
            except subprocess.TimeoutExpired as exc:
                results.append(
                    {
                        "command": command,
                        "gate_stage": (
                            "full" if index == len(commands) - 1
                            else "focused" if index == 0 else "scoped"
                        ),
                        "passed": False, "exit_code": 124,
                        "stdout": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
                        "stderr": (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "",
                        "timed_out": True,
                    }
                )
        return results

    @classmethod
    def _is_safe_command(cls, argv: list[str]) -> bool:
        if not argv:
            return False
        program = Path(argv[0]).name
        arguments = argv[1:]
        if program == "pytest":
            return True
        if program in {"python", "python3"}:
            return len(arguments) >= 2 and arguments[:2] in (
                ["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"]
            )
        allowed = cls.SAFE_ACTIONS.get(program)
        if allowed is None or not arguments:
            return False
        if program in {"npm", "pnpm"} and arguments[0] == "run":
            return len(arguments) >= 2 and arguments[1] in allowed
        return arguments[0] in allowed


class StudioExecutionService:
    MAX_REPAIRS = 3

    def __init__(
        self,
        store: StudioStore | None = None,
        *,
        runtime_factory: Callable[..., Any] | None = None,
        verifier: IndependentVerifier | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store or StudioStore()
        self.knowledge = KnowledgeService(self.store)
        self.runtime_factory = runtime_factory or CodexAppServerRuntime
        self.verifier = verifier or IndependentVerifier()
        self.cancel_checker = cancel_checker

    def execute_project(self, project_id: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        release = self.store.current_release(project_id)
        if release is None or release["status"] != "approved":
            raise Problem(
                "release_not_approved", "Approve the PRD and Release before coding",
                actionable=True,
            )
        prd = self.store.get_prd(project_id, release["prd_version"])
        if prd["status"] != "approved":
            raise Problem("prd_not_approved", "PRD approval is required before coding")
        self.store.update_project(project_id, state=StudioState.EXECUTING.value)
        git = GitWorktreeManager(project["workspace_path"], project_id, release["id"])
        integration = git.prepare()
        runtime = self.runtime_factory(
            load_config().execution,
            interaction_handler=self._interaction_handler(project_id),
        )
        probe = runtime.probe()
        if not probe.available:
            self.store.update_project(project_id, state=StudioState.BLOCKED.value)
            raise Problem(
                "codex_not_ready", "Codex App Server is not ready", probe.detail,
                actionable=True, suggested_actions=("login_codex", "test_runtime"),
            )
        completed = []
        try:
            for unit in self._ordered_units(project_id, release["id"]):
                self._assert_project_active(project_id, release["id"])
                if unit["status"] == "completed":
                    completed.append(unit)
                    continue
                completed.append(
                    self._execute_unit(runtime, git, project, prd, release, unit)
                )
            self.store.update_project(
                project_id, state=StudioState.KNOWLEDGE_DISTILLING.value
            )
            self.knowledge.capture(
                type="resolution", project_id=project_id,
                title=f"Release {release['id']} 通过独立验证",
                summary="所有获批 Feature 已实现并通过测试与 Detached Review。",
                observations=(f"集成分支：{git.integration_branch}",),
                confidence=1.0, validity="validated", generalizable=False,
                prd_version=release["prd_version"], release_id=release["id"],
                code_fingerprint=fingerprint_tree(integration).digest,
            )
            self.store.update_project(project_id, state=StudioState.DELIVERED.value)
            return {
                "project_id": project_id, "release_id": release["id"],
                "status": "delivered", "integration_branch": git.integration_branch,
                "integration_worktree": str(integration), "execution_units": completed,
            }
        except Exception as exc:
            current = self.store.get_project(project_id)
            superseded = isinstance(exc, Problem) and exc.code in {
                "execution_product_change_pending", "execution_release_superseded",
            }
            if not superseded and current["state"] not in {
                StudioState.BLOCKED.value,
                StudioState.PAUSED.value,
                StudioState.STOPPED.value,
            }:
                self.store.update_project(project_id, state=StudioState.BLOCKED.value)
            raise
        finally:
            runtime.close()

    def _execute_unit(
        self, runtime, git: GitWorktreeManager, project: dict[str, Any],
        prd: dict[str, Any], release: dict[str, Any], unit: dict[str, Any],
    ) -> dict[str, Any]:
        workspace, _branch = git.unit_worktree(unit["id"])
        self._assert_project_active(project["id"], release["id"])
        self.store.update_project(project["id"], state=StudioState.EXECUTING.value)
        baseline = fingerprint_tree(workspace).digest
        context = self.knowledge.context(
            " ".join((unit["title"], unit["objective"], *unit["acceptance"])),
            target_project_id=project["id"], phase="technical_plan",
            feature_id=unit["feature_id"],
            technology_stack=project["baseline"].get("technology_stack") or (),
        )
        request = ExecutionRequest(
            project_id=project["id"], run_id=release["id"],
            work_item_id=unit["id"], attempt=unit["attempt"] + 1,
            workspace=workspace, objective=unit["objective"],
            contract_id=release["id"], contract_version=release["prd_version"],
            baseline_fingerprint=baseline,
            instructions=(
                "Implement only the approved Feature. Product changes require a new PRD. "
                f"Acceptance: {json.dumps(unit['acceptance'], ensure_ascii=False)}"
            ),
            acceptance_rule_ids=tuple(
                f"{unit['feature_id']}:acceptance:{index}"
                for index, _ in enumerate(unit["acceptance"], start=1)
            ),
            expected_paths=tuple(unit["expected_paths"]),
            constraints=("No push, merge, deploy, or external side effects",),
            strategy=unit["strategy"], sanitized_knowledge_context=context["rendered"],
            session_id=unit["thread_id"],
        )
        self.store.update_execution_unit(unit["id"], status="executing", attempt=request.attempt)
        result = runtime.execute(
            request,
            event_sink=self._event_sink(
                runtime, project["id"], unit["id"], release["id"]
            ),
        )
        self._assert_project_active(project["id"], release["id"])
        persisted = next(
            value for value in self.store.execution_units(project["id"], release["id"])
            if value["id"] == unit["id"]
        )
        compiled_plan = persisted["plan"] or self._compile_plan_dag(unit, result.plan)
        unit = self.store.update_execution_unit(
            unit["id"], thread_id=result.session_id, plan=compiled_plan,
            status="verifying",
        )
        self.knowledge.capture_decision(
            project_id=project["id"],
            title=f"{unit['title']} 使用 Codex {unit['strategy']} 模式",
            selected=unit["strategy"], reason=unit["strategy_reason"],
            options=("direct", "plan_then_execute", "goal", "plan_then_goal"),
            prd_version=release["prd_version"], feature_id=unit["feature_id"],
            release_id=release["id"], execution_unit_id=unit["id"],
            thread_id=result.session_id, turn_id=result.turn_id,
        )
        if result.plan:
            self.knowledge.capture(
                type="discovery", project_id=project["id"],
                title=f"{unit['title']} 的 Codex 最终 Plan",
                summary="最终 Plan 已编译到 Feature 对齐的 ExecutionUnit。",
                inferences=tuple(str(value.get("step") or "") for value in result.plan),
                confidence=0.5, validity="observed", generalizable=False,
                prd_version=release["prd_version"], feature_id=unit["feature_id"],
                release_id=release["id"], execution_unit_id=unit["id"],
                thread_id=result.session_id, turn_id=result.turn_id,
            )
        after = fingerprint_tree(workspace).digest
        self.store.record_evidence(
            {
                "project_id": project["id"], "prd_version": release["prd_version"],
                "release_id": release["id"], "feature_id": unit["feature_id"],
                "execution_unit_id": unit["id"], "kind": "runtime_candidate",
                "trust": "candidate", "passed": not result.unresolved_blockers,
                "fingerprint": after,
                "detail": {
                    "summary": result.final_response, "turn_id": result.turn_id,
                    "codex_reported_files": list(result.changed_files),
                    "independent_diff": git.diff_summary(workspace),
                    "acceptance_rule_ids": list(request.acceptance_rule_ids),
                },
            }
        )
        request = replace(request, session_id=result.session_id)
        for repair in range(self.MAX_REPAIRS + 1):
            self._assert_project_active(project["id"], release["id"])
            evidence_ids = []
            artifact_refs = []
            gate_results = self.verifier.run(
                workspace, unit["verification_commands"]
            )
            for gate in gate_results:
                artifact = self.store.put_artifact(
                    project["id"], "verification_command_output",
                    json.dumps(
                        {
                            "command": gate["command"],
                            "stdout": gate.get("stdout") or "",
                            "stderr": gate.get("stderr") or "",
                        },
                        ensure_ascii=False,
                    ),
                    "application/json",
                )
                artifact_refs.append(artifact["id"])
                evidence_detail = {
                    key: value for key, value in gate.items()
                    if key not in {"stdout", "stderr"}
                }
                evidence_detail["artifact_ref"] = artifact["id"]
                evidence = self.store.record_evidence(
                    {
                        "project_id": project["id"], "prd_version": release["prd_version"],
                        "release_id": release["id"], "feature_id": unit["feature_id"],
                        "execution_unit_id": unit["id"], "kind": "command_result",
                        "trust": "verified" if gate["passed"] else "rejected",
                        "passed": gate["passed"], "fingerprint": fingerprint_tree(workspace).digest,
                        "detail": evidence_detail,
                    }
                )
                evidence_ids.append(evidence["id"])
            runtime_failure = None
            if result.unresolved_blockers:
                runtime_failure = {
                    "runtime_blockers": list(result.unresolved_blockers),
                    "turn_id": result.turn_id,
                }
            gate_failure = runtime_failure or next(
                (value for value in gate_results if not value["passed"]), None
            )
            review = None
            blockers = []
            if gate_failure is None:
                self.store.update_project(project["id"], state=StudioState.VERIFYING.value)
                review = runtime.review(
                    result.session_id, request,
                    event_sink=self._event_sink(
                        runtime, project["id"], unit["id"], release["id"],
                        review=True,
                    ),
                )
                blockers = [value for value in review.review_findings if value["blocking"]]
                review_evidence = self.store.record_evidence(
                    {
                        "project_id": project["id"], "prd_version": release["prd_version"],
                        "release_id": release["id"], "feature_id": unit["feature_id"],
                        "execution_unit_id": unit["id"], "kind": "detached_review",
                        "trust": "verified" if not blockers else "rejected",
                        "passed": not blockers, "fingerprint": fingerprint_tree(workspace).digest,
                        "detail": {
                            "summary": review.final_response,
                            "findings": list(review.review_findings),
                        },
                    }
                )
                evidence_ids.append(review_evidence["id"])
            if gate_failure is None and not blockers:
                if unit["strategy"] in {"goal", "plan_then_goal"}:
                    runtime.complete_goal(result.session_id)
                    self.knowledge.capture(
                        type="experiment", project_id=project["id"],
                        title=f"{unit['title']} 的 Goal 已在验收后完成",
                        summary="Goal 状态只在测试与 Detached Review 通过后标记 complete。",
                        observations=("独立质量门通过",),
                        confidence=1.0, validity="validated", generalizable=False,
                        prd_version=release["prd_version"],
                        feature_id=unit["feature_id"], release_id=release["id"],
                        execution_unit_id=unit["id"], thread_id=result.session_id,
                        turn_id=result.turn_id, evidence_ids=tuple(evidence_ids),
                    )
                commit = git.commit_and_integrate(workspace, unit["title"])
                self.store.record_evidence(
                    {
                        "project_id": project["id"], "prd_version": release["prd_version"],
                        "release_id": release["id"], "feature_id": unit["feature_id"],
                        "execution_unit_id": unit["id"], "kind": "integrated_commit",
                        "trust": "verified", "passed": True,
                        "fingerprint": fingerprint_tree(git.integration_path).digest,
                        "detail": {"commit": commit, "branch": git.integration_branch},
                    }
                )
                if repair:
                    self.knowledge.capture(
                        type="resolution", project_id=project["id"],
                        title=f"{unit['title']} 在修复后通过质量门",
                        summary=f"第 {repair} 轮 Repair 后测试与 Detached Review 全部通过。",
                        observations=("独立质量门通过", "P0/P1 Review blocker 已清零"),
                        confidence=1.0, validity="validated", generalizable=False,
                        prd_version=release["prd_version"],
                        feature_id=unit["feature_id"], release_id=release["id"],
                        execution_unit_id=unit["id"], thread_id=result.session_id,
                        turn_id=result.turn_id, evidence_ids=tuple(evidence_ids),
                        artifact_refs=tuple(artifact_refs),
                        code_fingerprint=fingerprint_tree(workspace).digest,
                    )
                return self.store.update_execution_unit(unit["id"], status="completed")
            if repair >= self.MAX_REPAIRS:
                detail = gate_failure or {"review_blockers": blockers}
                detail_text = sanitize_for_model(
                    json.dumps(detail, ensure_ascii=False), max_chars=8000
                )
                self.knowledge.capture_failure(
                    project_id=project["id"], title=f"{unit['title']} 未通过质量门",
                    symptom=detail_text,
                    attempted_fixes=(f"Codex repair attempt {value}" for value in range(1, repair + 1)),
                    feature_id=unit["feature_id"], release_id=release["id"],
                    execution_unit_id=unit["id"], thread_id=result.session_id,
                    evidence_ids=tuple(evidence_ids),
                    artifact_refs=tuple(artifact_refs),
                    code_fingerprint=fingerprint_tree(workspace).digest,
                )
                self.store.update_execution_unit(unit["id"], status="failed")
                raise Problem(
                    "verification_failed", "Feature failed independent verification",
                    detail_text, actionable=True,
                )
            failure_text = sanitize_for_model(
                json.dumps(
                    gate_failure or {"review_blockers": blockers}, ensure_ascii=False
                ),
                max_chars=8000,
            )
            self.knowledge.capture_failure(
                project_id=project["id"],
                title=f"{unit['title']} 第 {repair + 1} 次质量门失败",
                symptom=failure_text, attempted_fixes=tuple(
                    f"Repair {value}" for value in range(1, repair + 1)
                ),
                feature_id=unit["feature_id"], release_id=release["id"],
                execution_unit_id=unit["id"], thread_id=result.session_id,
                turn_id=result.turn_id, evidence_ids=tuple(evidence_ids),
                artifact_refs=tuple(artifact_refs),
                code_fingerprint=fingerprint_tree(workspace).digest,
            )
            repair_context = self.knowledge.context(
                failure_text, target_project_id=project["id"], phase="repair",
                feature_id=unit["feature_id"],
            )
            repair_request = replace(
                request, attempt=request.attempt + repair + 1, mode="repair",
                strategy="direct",
                feedback=(
                    "Independent verification failed. Repair the root cause without changing "
                    f"the approved product contract. Evidence: {failure_text}"
                ),
                sanitized_knowledge_context=repair_context["rendered"],
                baseline_fingerprint=fingerprint_tree(workspace).digest,
            )
            result = runtime.execute(
                repair_request,
                event_sink=self._event_sink(
                    runtime, project["id"], unit["id"], release["id"]
                ),
            )
        raise AssertionError("unreachable")

    def _assert_project_active(self, project_id: str, release_id: str = "") -> None:
        if self.cancel_checker is not None and self.cancel_checker():
            self.store.update_project(project_id, state=StudioState.STOPPED.value)
        state = self.store.get_project(project_id)["state"]
        if state == StudioState.PRD_REVIEW.value:
            raise Problem(
                "execution_product_change_pending",
                "Execution stopped because a new PRD requires approval",
                actionable=True,
                suggested_actions=("approve_prd",),
            )
        if release_id:
            current_release = self.store.current_release(project_id)
            if current_release is None or current_release["id"] != release_id:
                raise Problem(
                    "execution_release_superseded",
                    "Execution stopped because a newer Release was approved",
                    release_id,
                )
        if state in {StudioState.PAUSED.value, StudioState.STOPPED.value}:
            raise Problem(
                "execution_paused" if state == StudioState.PAUSED.value else "execution_stopped",
                "Execution paused by user" if state == StudioState.PAUSED.value else "Execution stopped by user",
                actionable=state == StudioState.PAUSED.value,
                suggested_actions=("resume",) if state == StudioState.PAUSED.value else (),
            )

    def _event_sink(
        self, runtime, project_id: str, unit_id: str, release_id: str,
        *, review: bool = False,
    ):
        def sink(event: dict[str, Any]) -> None:
            if event["type"] == "runtime.plan.finalized":
                self.store.update_execution_unit(
                    unit_id,
                    plan=self._compile_plan_dag(
                        {"id": unit_id},
                        tuple((event.get("payload") or {}).get("plan") or ()),
                    ),
                )
            self.store.append_event(
                event["type"],
                {
                    **event.get("payload", {}),
                    "execution_unit_id": unit_id,
                    "review": review,
                },
                project_id,
            )
            try:
                self._assert_project_active(project_id, release_id)
            except Problem:
                thread_id = str((event.get("payload") or {}).get("threadId") or "")
                if thread_id:
                    runtime.interrupt(thread_id)
                raise

        return sink

    @staticmethod
    def _compile_plan_dag(
        unit: dict[str, Any], plan: tuple[dict[str, Any], ...] | list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Compile the authoritative final Plan into bounded, ordered DAG nodes."""
        nodes = []
        previous = ""
        for index, value in enumerate(plan[:50], start=1):
            step = str(value.get("step") or "").strip()[:500]
            if not step:
                continue
            step_id = f"{unit['id']}:plan:{index}"
            nodes.append({
                "id": step_id,
                "execution_unit_id": unit["id"],
                "step": step,
                "status": "pending",
                "dependencies": [previous] if previous else [],
            })
            previous = step_id
        return nodes

    def _ordered_units(self, project_id: str, release_id: str) -> list[dict[str, Any]]:
        units = self.store.execution_units(project_id, release_id)
        by_feature = {unit["feature_id"]: unit for unit in units}
        ordered: list[dict[str, Any]] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(unit: dict[str, Any]) -> None:
            feature_id = unit["feature_id"]
            if feature_id in visited:
                return
            if feature_id in visiting:
                raise Problem("execution_dependency_cycle", "Feature dependency cycle", feature_id)
            visiting.add(feature_id)
            for dependency in unit["dependencies"]:
                if dependency in by_feature:
                    visit(by_feature[dependency])
            visiting.remove(feature_id)
            visited.add(feature_id)
            ordered.append(unit)

        for unit in units:
            visit(unit)
        return ordered

    def _interaction_handler(self, project_id: str):
        def handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
            if method not in {
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
                "item/permissions/requestApproval",
                "item/tool/requestUserInput",
                "mcpServer/elicitation/request",
            }:
                raise Problem("unsupported_codex_request", "Unsupported Codex request", method)
            prompt = str(params.get("reason") or params.get("message") or "")
            if method == "item/tool/requestUserInput":
                prompt = json.dumps(params.get("questions") or [], ensure_ascii=False)
            if method == "item/tool/requestUserInput":
                options = []
            elif method == "item/permissions/requestApproval":
                options = [
                    json.dumps(
                        {
                            "permissions": params.get("permissions") or {},
                            "scope": "turn",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {"permissions": {}, "scope": "turn"},
                        ensure_ascii=False,
                    ),
                ]
            else:
                options = params.get("availableDecisions") or ["accept", "decline"]
            interaction = self.store.create_interaction(
                {
                    "project_id": project_id,
                    "kind": "technical_question" if "requestUserInput" in method else "runtime_permission",
                    "prompt": prompt or method,
                    "options": [json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
                                for value in options],
                    "thread_id": str(params.get("threadId") or ""),
                    "turn_id": str(params.get("turnId") or ""),
                }
            )
            self.store.update_project(project_id, state=StudioState.BLOCKED.value)
            deadline = time.monotonic() + load_config().execution.codex_app_server_timeout_seconds
            while time.monotonic() < deadline:
                current = next(
                    value for value in self.store.interactions(project_id)
                    if value["id"] == interaction["id"]
                )
                if current["status"] == "resolved":
                    self.store.update_project(project_id, state=StudioState.EXECUTING.value)
                    response = current["response"]
                    if method == "item/tool/requestUserInput":
                        try:
                            answers = json.loads(response)
                        except json.JSONDecodeError:
                            questions = params.get("questions") or []
                            answers = {
                                str(question.get("id") or index): {"answers": [response]}
                                for index, question in enumerate(questions)
                            }
                        return {"answers": answers}
                    if method == "item/permissions/requestApproval":
                        try:
                            return json.loads(response)
                        except json.JSONDecodeError:
                            return {"permissions": {}, "scope": "turn"}
                    if method == "mcpServer/elicitation/request":
                        return {"action": "accept" if response != "decline" else "decline",
                                "content": None if response == "decline" else response, "_meta": None}
                    if response in {
                        "accept", "acceptForSession", "decline", "cancel"
                    }:
                        return {"decision": response}
                    try:
                        structured_decision = json.loads(response)
                    except json.JSONDecodeError:
                        structured_decision = "decline"
                    return {"decision": structured_decision}
                time.sleep(0.5)
            if method == "item/tool/requestUserInput":
                return {"answers": {}}
            if method == "item/permissions/requestApproval":
                return {"permissions": {}, "scope": "turn"}
            if method == "mcpServer/elicitation/request":
                return {"action": "decline", "content": None, "_meta": None}
            return {"decision": "decline"}

        return handle
