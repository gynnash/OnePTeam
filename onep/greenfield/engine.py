"""Autonomous single-writer Greenfield engineering orchestration."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import uuid

import click
from rich.console import Console
import yaml

from onep.config import load_config
from onep.greenfield.gates import (
    GreenfieldGateRunner, discover_quality_commands, validate_gate_commands,
)
from onep.greenfield.git_session import GreenfieldGitSession
from onep.greenfield.models import (
    AcceptanceContract, AcceptanceItem, GreenfieldOptions, GreenfieldRun,
    GreenfieldStage, GreenfieldStatus, SlicePlan,
)
from onep.greenfield.recorder import GreenfieldRecorder
from onep.llm.adapters import LLMAdapter
from onep.llm.cost import CostTracker
from onep.llm.router import resolve_model
from onep.persistence.database import update_project
from onep.persistence.models import Project, ProjectStatus
from onep.persistence.state import load_state, save_state
from onep.strategy.gates import PatchScopeGate, validate_focused_test_commands
from onep.strategy.models import StrategyItem
from onep.strategy.optimize_engine import OptimizeEngine
from onep.strategy.repair import (
    AttemptStagnationDetector, RepairBrief, previous_tool_actions,
)
from onep.strategy.reviewer import ReviewAgent


ENGINEER_SYSTEM = """You are the only write-capable Greenfield Engineer.
Own requirements, architecture, implementation, repair, and refactoring for the
entire run. Prefer mature, locally available technology and the simplest design
that satisfies the acceptance contract. Use tools to inspect and modify the
workspace. Never claim a gate passed; external processes and the read-only
reviewer decide that. Do not deploy externally or perform destructive actions."""

DISCOVERY_PROMPT = """Analyze this product requirement and current repository.
Return JSON only with keys:
acceptance: list of {{id, priority, behavior, verification:{{commands,evidence}}}},
architecture: {{constraints, candidates, selected, rationale, consequences}},
slices: list of {{id,title,objective,acceptance_ids,expected_files,focused_commands}}.
If a genuinely product-defining ambiguity cannot be inferred safely, return
{{"clarification_question":"one concise question"}} instead.
Use vertical slices. Include executable verification for every P0/P1 item.
focused_commands are fast, deterministic, offline test-runner commands only; do
not put live network collection, cron, report generation, or shell inspection in
focused_commands. Put those commands in acceptance verification instead.
Every Python entry command must name an exact module or file, for example
`python -m src.collect` or `python src/collect.py`, never `python src/collect`.
expected_files must include every production file, test, fixture, entry point,
package marker, and dependency manifest the slice may change. Do not include
runtime-generated files or directories such as tmp/*.json or report output paths.
Requirement: {requirement}
Repository summary:
{repository_summary}"""


class GreenfieldBlocked(RuntimeError):
    """The run needs one user decision before it can continue safely."""


class GreenfieldEngine:
    def __init__(self, console: Console | None = None, llm=None):
        self.console = console or Console()
        self.llm = llm or LLMAdapter()
        self.optimizer = OptimizeEngine()
        self.reviewer = ReviewAgent(self.llm)

    def run(
        self,
        project: Project,
        options: GreenfieldOptions | None = None,
    ) -> bool:
        workspace = Path(project.workspace_path).resolve()
        state = load_state(workspace)
        run = self._load_run(workspace, state)
        if run is None:
            run = GreenfieldRun(
                id=f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
                project_name=project.name,
                requirement=project.requirement,
                workspace=str(workspace),
                options=options or GreenfieldOptions(),
            )
            state.artifacts["greenfield_run_id"] = run.id
            state.artifacts["greenfield_options"] = run.options.to_dict()
            save_state(workspace, state)
        elif options is not None:
            run.options = options

        run_dir = workspace / ".onep" / "greenfield" / "runs" / run.id
        recorder = GreenfieldRecorder(run_dir, run, self.console)
        tracker = CostTracker(run.options.max_cost)
        self._round_start = run.round_number
        session = None
        try:
            self._validate_budget_pricing(run.options)
            session = GreenfieldGitSession(workspace, run.id)
            if run.run_branch:
                session.resume(run.run_branch)
            else:
                session.start()
                run.base_branch = session.base_branch
                run.base_commit = session.base_commit
                run.run_branch = session.run_branch
            run.status = GreenfieldStatus.RUNNING
            project.status = ProjectStatus.RUNNING
            update_project(project)
            recorder.save_run()

            contract = self._load_contract(run_dir)
            if not run.slices:
                contract = self._discover(run, workspace, recorder, tracker)
                if session.repo.is_dirty(untracked_files=True):
                    session.repo.git.add("docs/PRD.md", "docs/ARCHITECTURE.md")
                    session.repo.index.commit(
                        "docs: record acceptance and architecture baseline"
                    )
            elif contract is None:
                raise RuntimeError("acceptance contract missing from resumable run")

            self._sanitize_generated_commands(run, contract, recorder)
            self._normalize_slice_plans(run, contract, recorder)
            self._write_design_docs(
                workspace, run, contract, self._load_architecture(run_dir)
            )
            self._commit_design_docs(session)
            requirements_satisfied = self.build_pending_slices(
                run, contract, session, recorder, tracker
            )
            gate_runner = GreenfieldGateRunner(load_config().pipeline.test_timeout)

            mandatory = self._final_gate_commands(workspace, run, contract)
            self._final_verify(
                run, contract, session, mandatory, gate_runner, recorder, tracker
            )
            summary = self._write_completion_docs(
                run, contract, session.workspace, mandatory
            )
            documentation_commit = self._commit_completion_docs(session)
            run.stage = GreenfieldStage.FINISHED
            run.status = GreenfieldStatus.COMPLETED
            run.ended_at = datetime.now(timezone.utc).isoformat()
            run.spent = tracker.spent
            recorder.trace("FINISHED", "所有验收项、质量闸门和评审均已通过", "green")
            recorder.save_report(self._report(run, contract))
            recorder.save_run()
            project.status = ProjectStatus.COMPLETED
            project.current_stage = ""
            project.touch()
            update_project(project)
            self.console.print(
                f"[bold green]{summary}[/bold green]\n"
                f"[green]Documentation commit: {documentation_commit[:8]}[/green]\n"
                f"[green]Greenfield branch: {run.run_branch}[/green]\n"
                f"[dim]Review and merge it into {run.base_branch} when ready.[/dim]\n"
                f"[dim]Run records: {run_dir}[/dim]"
            )
            return True
        except GreenfieldBlocked as exc:
            return self._block(project, run, recorder, str(exc))
        except KeyboardInterrupt:
            if session is not None:
                session.rollback_attempt()
            return self._fail(project, run, recorder, "cancelled", "Run cancelled")
        except Exception as exc:
            if session is not None:
                session.rollback_attempt()
            return self._fail(
                project, run, recorder, self._failure_type(exc), str(exc)
            )

    def _discover(
        self, run: GreenfieldRun, workspace: Path,
        recorder: GreenfieldRecorder, tracker: CostTracker,
    ) -> AcceptanceContract:
        run.stage = GreenfieldStage.DISCOVER
        recorder.trace("DISCOVER", "正在分析需求、仓库环境和可用技术栈")
        summary = self._repository_summary(workspace)
        prompt = DISCOVERY_PROMPT.format(
            requirement=run.requirement, repository_summary=summary
        )
        for _ in range(2):
            output = self.llm.invoke(
                system_prompt=ENGINEER_SYSTEM,
                user_prompt=prompt,
                stage_name="greenfield_engineer",
            )
            self._track(tracker, "greenfield_engineer")
            data = self._json_object(output)
            question = str(data.get("clarification_question") or "").strip()
            if not question:
                break
            if run.options.non_interactive or not sys.stdin.isatty():
                raise GreenfieldBlocked(question)
            recorder.trace("INPUT", question, "yellow")
            answer = click.prompt(question)
            run.requirement += f"\n\nClarification: {answer}"
            prompt = DISCOVERY_PROMPT.format(
                requirement=run.requirement,
                repository_summary=summary,
            )
        else:
            raise GreenfieldBlocked("Requirement remains ambiguous after clarification")
        contract = AcceptanceContract.from_dict({
            "requirements": data.get("acceptance") or []
        })
        if not contract.items:
            contract = AcceptanceContract([AcceptanceItem(
                id="REQ-001", priority="P1", behavior=run.requirement,
            )])
        architecture = data.get("architecture") or {
            "constraints": [run.requirement],
            "candidates": [], "selected": "Engineer-selected minimal stack",
            "rationale": "Satisfy the acceptance contract with minimal complexity",
            "consequences": [],
        }
        slices = data.get("slices") or self._fallback_slices(contract)
        run.slices = [
            SlicePlan.from_dict(item, index) for index, item in enumerate(slices)
        ]
        run.stage = GreenfieldStage.PLAN_SLICES
        recorder.architecture_decision(architecture)
        recorder.save_contract(contract)
        self._write_design_docs(workspace, run, contract, architecture)
        for plan in run.slices:
            recorder.save_slice(plan)
        recorder.trace(
            "PLAN", f"已生成 {len(contract.items)} 个验收项和 {len(run.slices)} 个纵向切片"
        )
        recorder.save_run()
        return contract

    def _execute_slice(
        self, run: GreenfieldRun, plan: SlicePlan, contract: AcceptanceContract,
        session: GreenfieldGitSession, mandatory: list[str],
        gate_runner: GreenfieldGateRunner, recorder: GreenfieldRecorder,
        tracker: CostTracker, detector: AttemptStagnationDetector,
    ) -> None:
        feedback = ""
        last_events: tuple[dict, ...] = ()
        session.begin_attempt()
        restored = recorder.restore_wip(plan, session.workspace)
        if restored:
            recorder.trace(
                "RECOVER",
                f"已恢复上次失败前的 {len(restored)} 个 WIP 文件，继续实现而非从零开始",
                "green",
            )
        for repair in range(run.options.max_repairs_per_slice + 1):
            self._check_budget_rounds(run, tracker)
            run.round_number += 1
            plan.attempts += 1
            run.stage = GreenfieldStage.REPAIR if repair else GreenfieldStage.IMPLEMENT
            label = f"REPAIR {repair}/{run.options.max_repairs_per_slice}" if repair else "IMPLEMENT"
            recorder.trace(
                f"SLICE {run.current_slice + 1}/{len(run.slices)}",
                f"{label}: {plan.title}",
            )
            recorder.trace(
                "STATE",
                f"累计工程轮次 {run.round_number}；本次剩余 "
                f"{run.options.max_rounds - (run.round_number - self._round_start)}；"
                f"当前切片修复 {repair}/{run.options.max_repairs_per_slice}",
                "blue",
            )
            item = StrategyItem(
                id=plan.id, title=plan.title, file_location=",".join(plan.expected_files) or "N/A",
                summary=self._slice_prompt(run, plan, contract),
                tags=["greenfield", "vertical-slice"], impact="medium",
                expected_files=plan.expected_files,
            )
            item.summary += (
                "\nMandatory quality gates: "
                + ", ".join(mandatory or ["none discovered yet"])
                + "\nIf pytest is mandatory, create real pytest-discoverable test_*.py "
                "tests with test_* functions; a standalone verification script is not enough."
                "\nFinish implementation and fast local tests before reporting completion. "
                "Do not run live network acceptance commands; external gates own them."
                "\nWork in large, coherent batches: inspect only the files needed for this "
                "slice, then implement all planned production code and tests in the same "
                "attempt. Batch independent tool calls in one model round. Do not repeatedly "
                "audit the repository or run the full test suite; the external gate does that. "
                "Before using tools, briefly state the concrete implementation result you are "
                "about to produce."
            )
            recorder.begin_engineer_attempt()
            try:
                result = self.optimizer.execute_attempt(
                    item, str(session.workspace), str(session.workspace), self.llm,
                feedback=feedback,
                event_sink=recorder.engineer_event,
                verbose=run.options.verbose,
                max_tool_rounds=16,
                mutation_nudge_round=4,
                block_full_test_commands=True,
                )
            except BaseException:
                session.rollback_attempt()
                raise
            last_events = result.events
            self._track(tracker, "optimize_developer")
            changed = session.changed_files()
            diff = session.diff()
            recorder.engineer_summary(
                result.output, changed, result.termination_reason
            )
            failure_type = ""
            raw_error = ""
            failing_command = ""
            if result.termination_reason != "completed":
                failure_type = "implementation_incomplete"
                raw_error = (
                    "Engineer implementation did not finish: "
                    f"{result.termination_reason}. Continue from the existing changes "
                    "before running external quality gates."
                )
            elif not changed:
                failure_type, raw_error = "no_changes", "Engineer produced no code changes"
            elif plan.expected_files:
                candidate = self._scope_candidate(item, plan, contract)
                self._expand_scope_from_local_imports(
                    candidate, changed, session.workspace
                )
                self._expand_scope_for_tests(candidate, changed)
                scope = PatchScopeGate().check(
                    candidate, changed
                )
                if not scope.passed:
                    failure_type, raw_error = "scope_violation", scope.feedback

            tests = None
            if not failure_type:
                run.stage = GreenfieldStage.VERIFY_SLICE
                focused = self._fast_slice_commands(plan.focused_commands)
                all_mandatory = list(dict.fromkeys([
                    *discover_quality_commands(session.workspace), *mandatory,
                ]))
                current_mandatory = all_mandatory
                if focused:
                    current_mandatory = [
                        command for command in all_mandatory
                        if not self._is_broad_test_command(command)
                    ]
                recorder.trace(
                    "TEST",
                    f"实现已完成，执行 {len(focused) + len(current_mandatory)} 个快速质量闸门；"
                    f"{len(plan.focused_commands) - len(focused)} 个在线/验收命令延后到最终验收",
                )
                try:
                    tests = gate_runner.run(
                        session.workspace, focused, current_mandatory
                    )
                except ValueError as exc:
                    failure_type, raw_error = "test_failed", str(exc)
                else:
                    for command in tests.commands:
                        status = "passed" if command.passed else "failed"
                        recorder.trace(
                            "TEST", f"{command.command}: {status} ({command.duration_seconds:.1f}s)",
                            "green" if command.passed else "yellow",
                        )
                    if not tests.passed:
                        failed = next(cmd for cmd in tests.commands if not cmd.passed)
                        failure_type = "test_failed"
                        failing_command = failed.command
                        raw_error = failed.stdout + "\n" + failed.stderr

            review = None
            if not failure_type:
                run.stage = GreenfieldStage.REVIEW
                recorder.trace("REVIEW", "只读 Reviewer 正在检查逻辑、架构和回归风险")
                review = self.reviewer.review(
                    plan.objective, diff, self._test_summary(tests),
                    self._repository_summary(session.workspace),
                )
                self._track(tracker, "code_reviewer")
                recorder.save_review(plan, review.to_dict())
                if not review.passed:
                    failure_type = "review_failed"
                    raw_error = "\n".join(review.findings) or review.summary

            recorder.save_attempt(plan, plan.attempts, {
                "changed_files": changed,
                "test_results": [cmd.to_dict() for cmd in tests.commands] if tests else [],
                "review": review.to_dict() if review else None,
                "failure_type": failure_type,
                "failure_detail": raw_error,
                "trajectory": list(result.events),
            })
            if failure_type:
                recorder.save_wip(plan, changed, session.workspace)
            if not failure_type:
                plan.commit_sha = session.commit(f"feat: {plan.title}")
                plan.status = "completed"
                recorder.clear_wip(plan)
                recorder.save_diff(plan, diff)
                recorder.save_slice(plan)
                self._mark_acceptance(contract, plan, current_mandatory)
                recorder.save_contract(contract)
                recorder.trace("SLICE", f"{plan.title} 已通过并提交 {plan.commit_sha[:8]}", "green")
                recorder.save_run()
                return

            brief = RepairBrief.build(
                failure_type, raw_error, changed, diff,
                previous_tool_actions(last_events), failing_command,
            )
            recorder.event("repair_brief", brief.to_dict())
            if detector.observe(brief):
                session.rollback_attempt()
                raise RuntimeError(
                    "Loop stuck: the same failure and diff repeated 3 times. "
                    + brief.primary_error
                )
            feedback = brief.to_prompt()
            recorder.trace("REPAIR", f"{brief.failure_type}: {brief.primary_error[:240]}", "yellow")
            if repair >= run.options.max_repairs_per_slice:
                session.rollback_attempt()
                raise RuntimeError(
                    f"Repair attempts exhausted for {plan.id}: {brief.primary_error}"
                )
        raise RuntimeError(f"Slice did not converge: {plan.id}")

    def _final_verify(
        self, run: GreenfieldRun, contract: AcceptanceContract,
        session: GreenfieldGitSession, mandatory: list[str],
        gate_runner: GreenfieldGateRunner, recorder: GreenfieldRecorder,
        tracker: CostTracker, allow_repair: bool = True,
    ) -> None:
        run.stage = GreenfieldStage.FULL_VERIFY
        if not mandatory:
            raise RuntimeError("No mandatory quality gate discovered; pass --test-command")
        recorder.trace("FULL_VERIFY", "正在执行完整回归质量闸门")
        result = gate_runner.run(session.workspace, [], mandatory)
        if not result.passed:
            failed = next(cmd for cmd in result.commands if not cmd.passed)
            raise RuntimeError(
                f"Full verification failed: {failed.command}: "
                f"{(failed.stdout + failed.stderr)[-1500:]}"
            )
        if not contract.required_complete:
            raise RuntimeError(
                "P0/P1 acceptance items lack passing executable evidence"
            )
        run.stage = GreenfieldStage.ARCHITECTURE_REVIEW
        full_diff = session.repo.git.diff(run.base_commit, "HEAD")
        review = self.reviewer.review(
            "Final architecture and acceptance review", full_diff,
            self._test_summary(result), self._repository_summary(session.workspace),
        )
        self._track(tracker, "code_reviewer")
        if not review.passed:
            detail = "; ".join(review.findings) or review.summary
            if allow_repair:
                plan = SlicePlan(
                    id="final-architecture-hardening",
                    title="Final architecture hardening",
                    objective=(
                        "Resolve every blocking final architecture finding: "
                        + detail
                    ),
                    acceptance_ids=[], expected_files=[],
                )
                run.slices.append(plan)
                run.current_slice = len(run.slices) - 1
                recorder.save_slice(plan)
                self._execute_slice(
                    run, plan, contract, session, mandatory, gate_runner,
                    recorder, tracker, AttemptStagnationDetector(3),
                )
                refreshed = list(dict.fromkeys([
                    *discover_quality_commands(session.workspace), *mandatory,
                ]))
                return self._final_verify(
                    run, contract, session, refreshed, gate_runner,
                    recorder, tracker, allow_repair=False,
                )
            raise RuntimeError("Final architecture review failed: " + detail)
        run.stage = GreenfieldStage.DEPLOY_VERIFY
        recorder.trace("DEPLOY_VERIFY", f"部署模式: {run.options.deploy_mode}")
        deploy = gate_runner.deploy(session.workspace, run.options.deploy_mode)
        if deploy is not None and not deploy.passed:
            failed = next(cmd for cmd in deploy.commands if not cmd.passed)
            if allow_repair:
                plan = SlicePlan(
                    id="deployment-hardening",
                    title="Deployment hardening",
                    objective=(
                        f"Fix deployment verification failure for {failed.command}: "
                        + (failed.stdout + failed.stderr)[-1500:]
                    ),
                    acceptance_ids=[], expected_files=[],
                )
                run.slices.append(plan)
                run.current_slice = len(run.slices) - 1
                recorder.save_slice(plan)
                self._execute_slice(
                    run, plan, contract, session, mandatory, gate_runner,
                    recorder, tracker, AttemptStagnationDetector(3),
                )
                return self._final_verify(
                    run, contract, session, mandatory, gate_runner,
                    recorder, tracker, allow_repair=False,
                )
            raise RuntimeError(f"Deployment verification failed: {failed.command}")

    def _requirements_satisfied(
        self, run: GreenfieldRun, contract: AcceptanceContract,
        session: GreenfieldGitSession, gate_runner: GreenfieldGateRunner,
        recorder: GreenfieldRecorder, tracker: CostTracker,
    ) -> bool:
        """Check whether the repository already satisfies the complete requirement."""
        commands = self._final_gate_commands(session.workspace, run, contract)
        if not commands:
            return False
        fingerprint = self._assessment_fingerprint(session, commands, contract)
        if fingerprint == run.last_assessment_fingerprint:
            recorder.trace(
                "ASSESS",
                "代码和验收条件自上次检查后无变化，跳过重复完整评估",
                "dim",
            )
            return run.last_assessment_satisfied
        recorder.trace("ASSESS", "检查当前代码是否已经满足完整用户需求")
        missing = self._missing_command_paths(commands, session.workspace)
        if missing:
            previous = set(run.last_assessment_missing)
            resolved = sorted(previous - set(missing))
            if resolved:
                message = (
                    f"验收准备取得进展：新增满足 {len(resolved)} 项；"
                    f"仍缺少 {len(missing)} 项: " + ", ".join(missing[:8])
                )
            elif previous:
                message = f"本轮代码变化未减少验收前置项，仍缺少 {len(missing)} 项"
            else:
                message = (
                    "完整需求尚未具备验收条件，缺少: "
                    + ", ".join(missing[:8])
                )
            recorder.trace("ASSESS", message, "yellow")
            self._save_assessment(run, recorder, fingerprint, missing, False)
            return False
        try:
            result = gate_runner.run(session.workspace, [], commands)
        except ValueError as exc:
            recorder.trace("ASSESS", f"完整验收尚不可执行: {exc}", "yellow")
            self._save_assessment(run, recorder, fingerprint, [], False)
            return False
        if not result.passed:
            failed = next(command for command in result.commands if not command.passed)
            recorder.trace(
                "ASSESS", f"完整需求尚未满足: {failed.command}", "yellow"
            )
            self._save_assessment(run, recorder, fingerprint, [], False)
            return False
        acceptance = "\n".join(
            f"- {item.id} [{item.priority}]: {item.behavior}"
            for item in contract.items
        )
        full_diff = session.repo.git.diff(run.base_commit, "HEAD")
        review = self.reviewer.review(
            "Determine whether the complete repository satisfies the original "
            f"product requirement:\n{run.requirement}\n\nAcceptance contract:\n{acceptance}",
            full_diff,
            self._test_summary(result),
            self._repository_summary(session.workspace),
        )
        self._track(tracker, "code_reviewer")
        recorder.event("requirement_assessment", review.to_dict())
        if not review.passed:
            recorder.trace(
                "ASSESS", "完整需求评审仍有阻塞项", "yellow"
            )
            self._save_assessment(run, recorder, fingerprint, [], False)
            return False
        evidence = "full-requirement-assessment:gates-and-review-passed"
        executed = [command.command for command in result.commands]
        for item in contract.items:
            if item.priority in {"P0", "P1"}:
                item.status = "passed"
                item.commands = list(dict.fromkeys([*item.commands, *executed]))
                if evidence not in item.evidence:
                    item.evidence.append(evidence)
        recorder.save_contract(contract)
        self._save_assessment(run, recorder, fingerprint, [], True)
        return True

    @staticmethod
    def _save_assessment(
        run: GreenfieldRun, recorder: GreenfieldRecorder,
        fingerprint: str, missing: list[str], satisfied: bool,
    ) -> None:
        run.last_assessment_fingerprint = fingerprint
        run.last_assessment_missing = list(missing)
        run.last_assessment_satisfied = satisfied
        recorder.save_run()

    @staticmethod
    def _assessment_fingerprint(
        session: GreenfieldGitSession, commands: list[str],
        contract: AcceptanceContract,
    ) -> str:
        payload = {
            "head": session.repo.head.commit.hexsha,
            "status": session.repo.git.status("--porcelain"),
            "commands": commands,
            "required": [
                (item.id, item.priority, item.status)
                for item in contract.items if item.priority in {"P0", "P1"}
            ],
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _write_completion_docs(
        run: GreenfieldRun, contract: AcceptanceContract,
        workspace: Path, commands: list[str],
    ) -> str:
        workspace = Path(workspace)
        source_files = sorted(
            path.relative_to(workspace)
            for path in workspace.rglob("*")
            if path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(workspace).parts)
            and path.relative_to(workspace).parts[0] not in {"node_modules", "output"}
        )
        modules = []
        for relative in source_files:
            if relative.suffix not in {".py", ".js", ".ts", ".tsx", ".go", ".rs"}:
                continue
            description = "Project source module."
            if relative.suffix == ".py":
                try:
                    tree = ast.parse((workspace / relative).read_text(errors="replace"))
                    description = (ast.get_docstring(tree) or description).splitlines()[0]
                except (OSError, SyntaxError):
                    pass
            modules.append((relative.as_posix(), description))
        features = "\n".join(f"- {item.behavior}" for item in contract.items)
        structure = "\n".join(
            f"- `{path}` — {description}" for path, description in modules[:100]
        ) or "- See the repository source files."
        verification = "\n".join(f"- `{command}`" for command in commands)
        usage = next(
            (
                command for command in commands
                if not command.startswith(("pytest", "ruff", "mypy", "pyright"))
            ),
            "See `docs/CODE_GUIDE.md` for project entry points.",
        )
        if (workspace / "requirements.txt").exists():
            install = "python -m pip install -r requirements.txt"
        elif (workspace / "pyproject.toml").exists():
            install = "python -m pip install -e ."
        elif (workspace / "package.json").exists():
            install = "npm install"
        else:
            install = "No additional installation step was detected."
        readme = (
            f"# {run.project_name}\n\n"
            f"## Overview\n\n{run.requirement}\n\n"
            f"## Features\n\n{features}\n\n"
            f"## Installation\n\n```bash\n{install}\n```\n\n"
            f"## Usage\n\n```bash\n{usage}\n```\n\n"
            f"## Verification\n\n{verification}\n\n"
            "## Documentation\n\nSee [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) "
            "and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).\n"
        )
        guide = (
            f"# {run.project_name} Code Guide\n\n"
            f"## Product goal\n\n{run.requirement}\n\n"
            f"## Source modules\n\n{structure}\n\n"
            "## Delivery slices\n\n"
            + "\n".join(
                f"- **{plan.title}** (`{plan.status}`): {plan.objective}"
                for plan in run.slices
            )
            + f"\n\n## Acceptance and verification\n\n{features}\n\n{verification}\n"
        )
        (workspace / "README.md").write_text(readme, encoding="utf-8")
        docs = workspace / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "CODE_GUIDE.md").write_text(guide, encoding="utf-8")
        completed = sum(plan.status == "completed" for plan in run.slices)
        skipped = sum(plan.status == "skipped_satisfied" for plan in run.slices)
        return (
            f"需求已满足：{len(contract.items)} 个验收项通过，"
            f"{completed} 个切片完成，{skipped} 个剩余切片自动停止。"
        )

    @staticmethod
    def _commit_completion_docs(session: GreenfieldGitSession) -> str:
        paths = ["README.md", "docs/CODE_GUIDE.md"]
        status = session.repo.git.status("--porcelain", "--", *paths)
        if not status:
            return session.repo.head.commit.hexsha
        session.repo.git.add(*paths)
        return session.repo.index.commit(
            "docs: add project README and code guide"
        ).hexsha

    def _fail(
        self, project: Project, run: GreenfieldRun,
        recorder: GreenfieldRecorder, reason: str, detail: str,
    ) -> bool:
        run.status = (
            GreenfieldStatus.CANCELLED if reason == "cancelled"
            else GreenfieldStatus.FAILED
        )
        run.failure_reason = reason
        run.failure_detail = detail
        run.ended_at = datetime.now(timezone.utc).isoformat()
        recorder.event("run_failed", {"reason": reason, "detail": detail})
        recorder.save_report(self._error_report(run, recorder.run_dir))
        recorder.save_run()
        project.status = ProjectStatus.FAILED
        project.current_stage = run.stage.value
        project.touch()
        update_project(project)
        self.console.print(
            f"[bold red]ERROR [{reason.upper()}][/bold red]\n"
            f"原因: {detail}\n"
            f"建议:\n  1. 根据上述错误修正环境或需求\n"
            f"  2. 运行 onep run {project.name} 继续\n"
            f"记录: {recorder.run_dir / 'report.md'}"
        )
        return False

    def _block(
        self, project: Project, run: GreenfieldRun,
        recorder: GreenfieldRecorder, question: str,
    ) -> bool:
        run.status = GreenfieldStatus.BLOCKED
        run.blocked_question = question
        recorder.event("run_blocked", {"question": question})
        recorder.save_run()
        project.status = ProjectStatus.PAUSED
        project.current_stage = run.stage.value
        project.touch()
        update_project(project)
        self.console.print(
            f"[bold yellow]BLOCKED [NEEDS_INPUT][/bold yellow]\n"
            f"问题: {question}\n"
            f"建议: 在交互终端运行 onep run {project.name} 并回答问题\n"
            f"记录: {recorder.run_dir / 'run.yaml'}"
        )
        return False

    def _load_run(self, workspace: Path, state) -> GreenfieldRun | None:
        run_id = state.artifacts.get("greenfield_run_id")
        if not run_id:
            return None
        return GreenfieldRecorder.load(
            workspace / ".onep" / "greenfield" / "runs" / run_id / "run.yaml"
        )

    @staticmethod
    def _load_contract(run_dir: Path) -> AcceptanceContract | None:
        path = run_dir / "acceptance.yaml"
        if not path.exists():
            return None
        return AcceptanceContract.from_dict(yaml.safe_load(path.read_text()) or {})

    @staticmethod
    def _load_architecture(run_dir: Path) -> dict:
        path = Path(run_dir) / "architecture-decisions.jsonl"
        if path.exists():
            for line in reversed(path.read_text(errors="replace").splitlines()):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return value
        return {
            "selected": "Repository architecture derived from the acceptance contract",
            "rationale": "Preserve the resumable plan and implement the smallest viable design",
        }

    @staticmethod
    def _json_object(output: str) -> dict:
        match = re.search(r"\{.*\}", output or "", re.DOTALL)
        if not match:
            raise RuntimeError("Engineer discovery did not return structured JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Engineer discovery returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Engineer discovery result must be an object")
        return data

    @staticmethod
    def _repository_summary(workspace: Path) -> str:
        names = []
        for path in sorted(workspace.iterdir()):
            if path.name in {".git", ".onep", "node_modules", ".venv"}:
                continue
            names.append(path.name + ("/" if path.is_dir() else ""))
        return "Workspace files: " + ", ".join(names[:100])

    @staticmethod
    def _fallback_slices(contract: AcceptanceContract) -> list[dict]:
        ids = [item.id for item in contract.items]
        return [
            {"id": "foundation", "title": "Runnable foundation", "objective": "Create the smallest runnable architecture and test harness", "acceptance_ids": [], "expected_files": [], "focused_commands": []},
            {"id": "core", "title": "Core product behavior", "objective": "Implement all required user-visible behavior", "acceptance_ids": ids, "expected_files": [], "focused_commands": []},
            {"id": "hardening", "title": "Safety and operational hardening", "objective": "Add edge cases, errors, observability, and deployment support", "acceptance_ids": ids, "expected_files": [], "focused_commands": []},
        ]

    @staticmethod
    def _write_design_docs(
        workspace: Path, run: GreenfieldRun, contract: AcceptanceContract,
        architecture: dict,
    ) -> None:
        docs = workspace / "docs"
        docs.mkdir(exist_ok=True)
        acceptance_lines = "\n\n".join(
            f"### {item.id} [{item.priority}]\n\n{item.behavior}\n\n"
            + ("Verification:\n" + "\n".join(
                f"- `{command}`" for command in item.commands
            ) if item.commands else "Verification: reviewer evidence and project quality gates")
            for item in contract.items
        )
        (docs / "PRD.md").write_text(
            f"# {run.project_name} Product Requirements\n\n"
            f"## Product goal\n\n{run.requirement}\n\n"
            "## Definition of done\n\nAll P0/P1 acceptance items must have passing "
            "executable evidence, the complete quality suite must pass, and the "
            "read-only reviewer must report no blocking issue.\n\n"
            f"## Acceptance contract\n\n{acceptance_lines}\n",
            encoding="utf-8",
        )
        (docs / "ARCHITECTURE.md").write_text(
            "# Architecture\n\n```yaml\n"
            + yaml.safe_dump(architecture, allow_unicode=True, sort_keys=False)
            + "```\n",
            encoding="utf-8",
        )
        plan_sections = []
        for index, plan in enumerate(run.slices, 1):
            acceptance = ", ".join(plan.acceptance_ids) or "architecture/support"
            files = "\n".join(f"- `{value}`" for value in plan.expected_files)
            fast_commands = GreenfieldEngine._fast_slice_commands(
                plan.focused_commands
            )
            deferred_commands = [
                command for command in plan.focused_commands
                if command not in fast_commands
            ]
            fast = "\n".join(
                f"- `{command}`" for command in fast_commands
            ) or "- Project mandatory test gates (for example `pytest -q`)"
            deferred = "\n".join(
                f"- `{command}`" for command in deferred_commands
            ) or "- None"
            plan_sections.append(
                f"## Slice {index}: {plan.title}\n\n"
                f"**Objective:** {plan.objective}\n\n"
                f"**Acceptance:** {acceptance}\n\n"
                "### Implementation contract\n\n"
                f"{files or '- Infer the minimal repository files'}\n\n"
                "### Fast deterministic tests\n\n"
                f"{fast}\n\n"
                "### Deferred live/acceptance commands\n\n"
                f"{deferred}\n\n"
                "### Completion rule\n\nImplementation must finish without a tool-loop "
                "limit, all declared files must be present, and fast tests must pass "
                "before live acceptance is attempted.\n"
            )
        (docs / "IMPLEMENTATION_PLAN.md").write_text(
            f"# {run.project_name} Implementation Plan\n\n"
            "Live network and operational acceptance commands run only during the "
            "complete requirement assessment/final verification.\n\n"
            + "\n".join(plan_sections),
            encoding="utf-8",
        )

    @staticmethod
    def _commit_design_docs(session: GreenfieldGitSession) -> str:
        paths = [
            "docs/PRD.md", "docs/ARCHITECTURE.md",
            "docs/IMPLEMENTATION_PLAN.md",
        ]
        status = session.repo.git.status("--porcelain", "--", *paths)
        if not status:
            return session.repo.head.commit.hexsha
        session.repo.git.add(*paths)
        return session.repo.index.commit(
            "docs: persist detailed product and implementation plan"
        ).hexsha

    def build_pending_slices(
        self,
        run: GreenfieldRun,
        contract: AcceptanceContract,
        session: GreenfieldGitSession,
        recorder: GreenfieldRecorder,
        tracker: CostTracker,
        respect_satisfied_early_exit: bool = True,
    ) -> bool:
        """Execute pending slices until satisfied or exhausted.

        The harness passes respect_satisfied_early_exit=False for
        post-acceptance iterations whose new slices expand scope beyond
        the original contract.
        """
        workspace = session.workspace
        mandatory = self._slice_gate_commands(workspace, run)
        gate_runner = GreenfieldGateRunner(load_config().pipeline.test_timeout)
        detector = AttemptStagnationDetector(3)
        if respect_satisfied_early_exit and self._requirements_satisfied(
            run, contract, session, gate_runner, recorder, tracker
        ):
            return True
        for index in range(run.current_slice, len(run.slices)):
            plan = run.slices[index]
            if plan.status == "completed":
                continue
            run.current_slice = index
            self._execute_slice(
                run, plan, contract, session, mandatory, gate_runner,
                recorder, tracker, detector,
            )
            mandatory = self._slice_gate_commands(workspace, run)
            if (
                respect_satisfied_early_exit
                and contract.required_complete
                and self._requirements_satisfied(
                    run, contract, session, gate_runner, recorder, tracker
                )
            ):
                for remaining in run.slices[index + 1 :]:
                    if remaining.status == "pending":
                        remaining.status = "skipped_satisfied"
                        recorder.save_slice(remaining)
                recorder.trace(
                    "SATISFIED", "完整需求已经通过验收，停止执行剩余切片", "green"
                )
                return True
        return self._requirements_satisfied(
            run, contract, session, gate_runner, recorder, tracker
        )

    @staticmethod
    def _slice_prompt(
        run: GreenfieldRun, plan: SlicePlan, contract: AcceptanceContract,
    ) -> str:
        acceptance = [
            item.to_dict() for item in contract.items
            if item.id in plan.acceptance_ids
        ]
        return (
            f"Product requirement: {run.requirement}\n"
            f"Slice objective: {plan.objective}\n"
            f"Acceptance items: {json.dumps(acceptance, ensure_ascii=False)}\n"
            f"Expected files: {', '.join(plan.expected_files) or 'infer minimal files'}\n"
            "Implement production-quality code and tests. Inspect the current repository first. "
            "Do not merely describe code: use tools to write and verify it."
        )

    @staticmethod
    def _scope_candidate(
        item: StrategyItem, plan: SlicePlan,
        contract: AcceptanceContract | None = None,
    ):
        from onep.strategy.optimize_models import PlanCandidate
        files = {Path(value) for value in plan.expected_files}
        commands = list(plan.focused_commands)
        if contract is not None:
            commands.extend(
                command
                for acceptance in contract.items
                if acceptance.id in plan.acceptance_ids
                for command in acceptance.commands
            )
        module_roots = {
            path.parts[0] for path in files if len(path.parts) > 1
        }
        files.update(GreenfieldEngine._command_paths(commands, module_roots))
        for path in tuple(files):
            for parent in path.parents:
                if str(parent) == ".":
                    break
                files.add(parent / "__init__.py")
        files.update(Path(value) for value in (
            "requirements.txt", "pyproject.toml", "setup.cfg", "pytest.ini",
            "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
            "go.mod", "go.sum", "Cargo.toml", "Cargo.lock",
        ))
        return PlanCandidate(
            id=item.id, title=item.title, summary=item.summary,
            files=files,
        )

    @staticmethod
    def _command_paths(
        commands: list[str], module_roots: set[str] | None = None,
    ) -> set[Path]:
        paths: set[Path] = set()
        module_roots = module_roots or set()
        for command in commands:
            try:
                parts = shlex.split(command)
            except ValueError:
                continue
            for value in parts[1:]:
                if (
                    not value or value.startswith("-") or "://" in value
                    or value.startswith("/") or ".." in Path(value).parts
                ):
                    continue
                path = Path(value)
                if "/" in value or path.suffix in {
                    ".py", ".json", ".yaml", ".yml", ".db", ".md", ".sh",
                }:
                    paths.add(path)
                for module in re.findall(
                    r"\b(?:from|import)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
                    value,
                ):
                    if module.split(".", 1)[0] in module_roots:
                        paths.add(
                            Path(*module.split(".")).with_suffix(".py")
                        )
            if (
                len(parts) > 1 and parts[0] in {"python", "python3"}
                and not parts[1].startswith("-") and "/" in parts[1]
                and Path(parts[1]).suffix == ""
            ):
                paths.discard(Path(parts[1]))
                paths.add(Path(parts[1]).with_suffix(".py"))
        return paths

    @staticmethod
    def _expand_scope_from_local_imports(
        candidate, changed_files: list[str], workspace: Path,
    ) -> None:
        """Allow local Python modules imported by already-declared changed files."""
        workspace = Path(workspace)
        changed = {Path(value) for value in changed_files}
        pending = [
            path for path in changed
            if path in candidate.files and path.suffix == ".py"
        ]
        visited: set[Path] = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            source_path = workspace / source
            if not source_path.is_file():
                continue
            try:
                tree = ast.parse(source_path.read_text(errors="replace"))
            except SyntaxError:
                continue
            imports: list[Path] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(
                        Path(*alias.name.split(".")) for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        anchor = source.parent
                        for _ in range(node.level - 1):
                            anchor = anchor.parent
                    else:
                        anchor = Path()
                    module = Path(*(node.module or "").split("."))
                    imports.append(anchor / module)
            for module in imports:
                choices = [module.with_suffix(".py"), module / "__init__.py"]
                target = next(
                    (path for path in choices if (workspace / path).is_file()), None
                )
                if target is None:
                    continue
                candidate.files.add(target)
                for parent in target.parents:
                    if str(parent) == ".":
                        break
                    init = parent / "__init__.py"
                    if (workspace / init).is_file():
                        candidate.files.add(init)
                if target in changed and target not in visited:
                    pending.append(target)

    @staticmethod
    def _expand_scope_for_tests(candidate, changed_files: list[str]) -> None:
        """Allow conventional tests and fixtures required by mandatory test gates."""
        for value in changed_files:
            path = Path(value)
            if not path.parts or path.parts[0] not in {"test", "tests"}:
                continue
            is_test = path.suffix == ".py" and (
                path.name.startswith("test_") or path.name == "conftest.py"
            )
            is_fixture = path.suffix in {".json", ".yaml", ".yml", ".toml", ".txt"}
            if not (is_test or is_fixture or path.name == "__init__.py"):
                continue
            candidate.files.add(path)
            for parent in path.parents:
                if str(parent) == ".":
                    break
                candidate.files.add(parent / "__init__.py")

    @staticmethod
    def _sanitize_generated_commands(
        run: GreenfieldRun, contract: AcceptanceContract,
        recorder: GreenfieldRecorder,
    ) -> None:
        def safe(commands: list[str]) -> list[str]:
            accepted = []
            for command in commands:
                try:
                    validate_gate_commands([command])
                except ValueError as exc:
                    recorder.trace("PLAN", f"忽略不安全的生成命令: {exc}", "yellow")
                else:
                    accepted.append(command)
            return list(dict.fromkeys(accepted))

        for plan in run.slices:
            plan.focused_commands = safe(plan.focused_commands)
            recorder.save_slice(plan)
        for item in contract.items:
            item.commands = safe(item.commands)
        recorder.save_contract(contract)
        recorder.save_run()

    @staticmethod
    def _normalize_python_command(command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return command
        if (
            len(parts) >= 2 and parts[0] in {"python", "python3"}
            and not parts[1].startswith("-") and "/" in parts[1]
            and Path(parts[1]).suffix == ""
        ):
            parts[1] += ".py"
            return shlex.join(parts)
        return command

    @classmethod
    def _normalize_slice_plans(
        cls, run: GreenfieldRun, contract: AcceptanceContract,
        recorder: GreenfieldRecorder,
    ) -> None:
        for item in contract.items:
            item.commands = [cls._normalize_python_command(cmd) for cmd in item.commands]
        for plan in run.slices:
            plan.focused_commands = [
                cls._normalize_python_command(cmd) for cmd in plan.focused_commands
            ]
            commands = list(plan.focused_commands)
            commands.extend(
                command for item in contract.items
                if item.id in plan.acceptance_ids for command in item.commands
            )
            files = {Path(value) for value in plan.expected_files}
            roots = {path.parts[0] for path in files if len(path.parts) > 1}
            files.update(cls._command_paths(commands, roots))
            runtime_outputs = cls._runtime_output_paths(commands)
            files = {
                path for path in files
                if path not in runtime_outputs and not cls._is_runtime_artifact(path)
            }
            production = [
                path for path in files
                if path.suffix == ".py" and path.parts[0] not in {"test", "tests"}
                and path.name != "__init__.py"
            ]
            test_files = set()
            collector_files = [path for path in production if "collectors" in path.parts]
            if collector_files:
                test_files.add(Path("tests/test_collectors.py"))
            for path in production:
                if "collectors" not in path.parts:
                    test_files.add(Path("tests") / f"test_{path.stem}.py")
            if any(
                command.startswith(("pytest", "python -m pytest", "python3 -m pytest"))
                for command in run.options.test_commands
            ):
                files.update(test_files)
                files.add(Path("tests/__init__.py"))
            plan.expected_files = sorted(path.as_posix() for path in files)
            recorder.save_slice(plan)
        recorder.save_contract(contract)
        recorder.save_run()

    @staticmethod
    def _fast_slice_commands(commands: list[str]) -> list[str]:
        fast = []
        for command in commands:
            try:
                validate_focused_test_commands((command,))
            except ValueError:
                continue
            fast.append(command)
        return fast

    @classmethod
    def _missing_command_paths(
        cls, commands: list[str], workspace: Path,
    ) -> list[str]:
        paths = cls._required_command_paths(commands)
        missing = []
        for path in sorted(paths):
            if any(char in str(path) for char in "*?["):
                if not list(Path(workspace).glob(str(path))):
                    missing.append(str(path))
            elif not (Path(workspace) / path).exists():
                missing.append(str(path))
        return missing

    _OUTPUT_FLAGS = {
        "--output", "-o", "--out", "--output-dir", "--out-dir",
        "--report-dir", "--destination", "--dest",
    }

    @classmethod
    def _runtime_output_paths(cls, commands: list[str]) -> set[Path]:
        outputs: set[Path] = set()
        for command in commands:
            try:
                parts = shlex.split(command)
            except ValueError:
                continue
            for value in parts:
                for flag in cls._OUTPUT_FLAGS:
                    prefix = flag + "="
                    if value.startswith(prefix) and value[len(prefix):]:
                        outputs.add(Path(value[len(prefix):]))
            for index, value in enumerate(parts[:-1]):
                if value in cls._OUTPUT_FLAGS:
                    candidate = parts[index + 1]
                    if candidate and not candidate.startswith("-"):
                        outputs.add(Path(candidate))
        return outputs

    @staticmethod
    def _is_runtime_artifact(path: Path) -> bool:
        return bool(path.parts) and path.parts[0] in {
            "tmp", "temp", ".tmp", ".cache"
        }

    @classmethod
    def _required_command_paths(cls, commands: list[str]) -> set[Path]:
        return cls._command_paths(commands) - cls._runtime_output_paths(commands)

    @staticmethod
    def _is_broad_test_command(command: str) -> bool:
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
            args = parts[3:]
        elif parts and parts[0] == "pytest":
            args = parts[1:]
        else:
            return False
        targets = [
            value for value in args
            if not value.startswith("-")
            and not re.fullmatch(r"\d*(?:>|<|>>|<<)&?\d*", value)
        ]
        return not targets or all(
            value.rstrip("/") in {".", "test", "tests"}
            for value in targets
        )

    @staticmethod
    def _slice_gate_commands(workspace: Path, run: GreenfieldRun) -> list[str]:
        return list(dict.fromkeys([
            *discover_quality_commands(workspace), *run.options.test_commands,
        ]))

    @staticmethod
    def _final_gate_commands(
        workspace: Path, run: GreenfieldRun, contract: AcceptanceContract,
    ) -> list[str]:
        return list(dict.fromkeys([
            *discover_quality_commands(workspace),
            *(command for item in contract.items for command in item.commands),
            *(command for plan in run.slices for command in plan.focused_commands),
            *run.options.test_commands,
        ]))

    @staticmethod
    def _mark_acceptance(
        contract: AcceptanceContract, plan: SlicePlan, commands: list[str],
    ) -> None:
        for item in contract.items:
            if item.id in plan.acceptance_ids:
                item.status = "passed"
                item.commands = list(dict.fromkeys([*item.commands, *commands]))
                item.evidence.append(f"slice:{plan.id}:gates-passed")

    @staticmethod
    def _test_summary(result) -> str:
        if result is None:
            return "No tests executed"
        return "\n".join(
            f"{cmd.command}: exit={cmd.exit_code}, duration={cmd.duration_seconds:.2f}s"
            for cmd in result.commands
        )

    def _track(self, tracker: CostTracker, stage: str) -> None:
        model = resolve_model(stage)[0]
        tracker.record_usage(stage, model, self.llm.last_usage)
        if not tracker.can_continue():
            raise RuntimeError(f"Cost budget exhausted: {tracker.summary()}")

    @staticmethod
    def _validate_budget_pricing(options: GreenfieldOptions) -> None:
        if options.max_cost <= 0:
            return
        config = load_config()
        missing = []
        for stage in ("greenfield_engineer", "optimize_developer", "code_reviewer"):
            model = resolve_model(stage)[0]
            pricing = config.llm.pricing.get(model) or {}
            if not pricing.get("input") or not pricing.get("output"):
                missing.append(model)
        if missing:
            raise RuntimeError(
                "Missing model pricing required for --max-cost: "
                + ", ".join(sorted(set(missing)))
            )

    def _check_budget_rounds(
        self, run: GreenfieldRun, tracker: CostTracker,
    ) -> None:
        if run.round_number - self._round_start >= run.options.max_rounds:
            raise RuntimeError(f"Maximum engineering rounds reached: {run.options.max_rounds}")
        if not tracker.can_continue():
            raise RuntimeError(f"Cost budget exhausted: {tracker.summary()}")

    @staticmethod
    def _failure_type(exc: Exception) -> str:
        value = str(exc).lower()
        if "dirty" in value or "detached" in value or "bare" in value:
            return "git_safety"
        if "budget" in value or "maximum engineering rounds" in value:
            return "budget_exhausted"
        if "gate" in value or "test" in value or "verification" in value:
            return "test_failed"
        if "stuck" in value:
            return "stuck"
        return "internal_error"

    @staticmethod
    def _report(run: GreenfieldRun, contract: AcceptanceContract) -> str:
        return (
            f"# Greenfield Run {run.id}\n\nStatus: completed\n\n"
            f"Branch: `{run.run_branch}`\n\n"
            f"Slices: {len(run.slices)}\n\n"
            f"Acceptance items passed: {sum(i.status == 'passed' for i in contract.items)}/{len(contract.items)}\n"
        )

    @staticmethod
    def _error_report(run: GreenfieldRun, run_dir: Path) -> str:
        return (
            f"# Greenfield Run {run.id}\n\nStatus: {run.status.value}\n\n"
            f"Stage: {run.stage.value}\n\nFailure: {run.failure_reason}\n\n"
            f"{run.failure_detail}\n\nResume: `onep run {run.project_name}`\n\n"
            f"Records: `{run_dir}`\n"
        )
