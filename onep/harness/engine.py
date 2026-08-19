"""Harness engine — orchestrates the unified autonomous development loop."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from rich.console import Console

from onep.config import load_config
from onep.greenfield.engine import GreenfieldBlocked, GreenfieldEngine
from onep.greenfield.gates import GreenfieldGateRunner
from onep.greenfield.git_session import GreenfieldGitSession
from onep.greenfield.models import (
    AcceptanceContract,
    AcceptanceItem,
    GreenfieldOptions,
    GreenfieldRun,
    GreenfieldStage,
    GreenfieldStatus,
)
from onep.greenfield.recorder import GreenfieldRecorder
from onep.harness.cross_project import CrossProjectDistiller
from onep.harness.design import DesignStage
from onep.harness.discover import BrainstormStage, PrioritizeStage
from onep.harness.distiller import KnowledgeDistiller
from onep.harness.interventions import apply_candidate_decisions
from onep.harness.knowledge_models import (
    load_run_events,
    save_distillations,
)
from onep.harness.research import ResearchStage
from onep.harness.scorer import OpportunityScorer
from onep.harness.vault import VaultWriter, global_vault_root, project_vault_root
from onep.harness.models import (
    CandidateAdapter,
    HarnessOptions,
    HarnessRun,
    SliceAdapter,
    StopReason,
    candidate_to_slice,
)
from onep.harness.persistence import (
    HarnessStateCorrupt,
    clear_stop_request,
    load_harness_run,
    save_harness_run,
    stop_requested,
)
from onep.harness.brownfield import (
    BrownfieldBuildStage,
    BrownfieldUnderstandStage,
)
from onep.harness.reflect import ReflectStage, evaluate_stop
from onep.harness.states import HarnessFlow, HarnessStage
from onep.harness.understand import (
    UnderstandStage,
    detect_mode,
)
from onep.llm.adapters import LLMAdapter
from onep.llm.cost import CostTracker
from onep.persistence.database import update_project
from onep.persistence.models import Project, ProjectStatus
from onep.persistence.state import load_state
from onep.strategy.analyze_pipeline import analyze_source
from onep.strategy.gates import discover_required_test_commands
from onep.strategy.models import StrategyItem
from onep.strategy.planner import generate_optimize_plan
from onep.strategy.reviewer import ReviewAgent
from onep.strategy.test_runner import PlanTestRunner


class HarnessEngine:
    """Top-level orchestrator: Product Loop around the Execution Kernel."""

    def __init__(
        self,
        console: Console | None = None,
        llm=None,
        vault_root: Path | None = None,
    ):
        self.console = console or Console()
        self.llm = llm or LLMAdapter()
        self.vault_root = (
            Path(vault_root).resolve()
            if vault_root is not None
            else global_vault_root()
        )
        self.kernel = GreenfieldEngine(self.console, self.llm)
        self.research = ResearchStage(self.llm, track=self.kernel._track)
        self.design = DesignStage(self.llm, track=self.kernel._track)
        self.scorer = OpportunityScorer(self.llm, track=self.kernel._track)
        self.knowledge = KnowledgeDistiller(self.llm, track=self.kernel._track)
        self.writer = VaultWriter(self.vault_root)

    def run(
        self,
        project: Project,
        options: GreenfieldOptions | None = None,
    ) -> bool:
        workspace = Path(project.workspace_path).resolve()
        try:
            run = load_harness_run(workspace)
        except HarnessStateCorrupt as exc:
            self.console.print(f"[red]无法恢复 Harness 状态: {exc}[/red]")
            project.status = ProjectStatus.FAILED
            project.current_stage = "failed"
            project.touch()
            update_project(project)
            return False
        if run is None:
            mode = detect_mode(workspace, project.requirement)
            run = HarnessRun(
                id=f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
                project_name=project.name,
                workspace=str(workspace),
                mode=mode,
                original_goal=project.requirement,
                options=HarnessOptions.from_greenfield(options or GreenfieldOptions()),
            )
            save_harness_run(run)
        elif options is not None:
            run.options = HarnessOptions.from_greenfield(options)
        if run.mode != "greenfield":
            detected = detect_mode(workspace, run.original_goal)
            if detected == "greenfield":
                # BROWNFIELD project with no code: treat as greenfield.
                run.mode = "greenfield"
                save_harness_run(run)
            else:
                run.mode = detected
                save_harness_run(run)
                if detected == "brownfield":
                    return self._run_brownfield(project, run, workspace, options)
                # Existing code plus an explicit requirement is a gap-analysis
                # build, not a generic optimization scan. Reuse the greenfield
                # acceptance/slice kernel against the existing repository so
                # the user's requirement remains the source of truth.

        gf_run = run.greenfield_run
        if gf_run is None:
            gf_run = self._adopt_legacy_run(workspace)
            if gf_run is None:
                gf_run = GreenfieldRun(
                    id=f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
                    project_name=project.name,
                    requirement=project.requirement,
                    workspace=str(workspace),
                    options=options or GreenfieldOptions(),
                )
            run.greenfield_run = gf_run
        elif options is not None:
            gf_run.options = options

        run_dir = workspace / ".onep" / "greenfield" / "runs" / gf_run.id
        recorder = GreenfieldRecorder(run_dir, gf_run, self.console)
        tracker = CostTracker(run.options.max_cost)
        self.writer.project_root = project_vault_root(workspace)

        def distill_checkpoint(checkpoint: str, payload: dict) -> None:
            try:
                if checkpoint == "round_end":
                    all_events = list(load_run_events(run_dir))
                    collected = all_events[run.knowledge_cursor :]
                    next_knowledge_cursor = len(all_events)
                    payload = dict(payload)
                    payload["slices"] = [
                        {
                            "id": plan.id,
                            "title": plan.title,
                            "status": plan.status,
                            "attempts": plan.attempts,
                        }
                        for plan in (gf_run.slices if gf_run else [])
                    ]
                    collected.append(payload)
                else:
                    collected = [payload]
                events = self.knowledge.distill(
                    raw_events=collected,
                    checkpoint=checkpoint,
                    iteration=run.iteration,
                    context=(
                        f"project: {run.project_name}\n"
                        f"goal: {run.original_goal or '(none)'}"
                    ),
                    tracker=tracker,
                    collapse=(checkpoint == "round_end"),
                )
                if checkpoint == "round_end":
                    run.knowledge_cursor = next_knowledge_cursor
                if not events:
                    return
                distilled = [event.to_dict() for event in events]
                run.knowledge_events.extend(distilled)
                for event in distilled:
                    bucket = {
                        "decision": run.decisions,
                        "experiment": run.experiments,
                        "failure": run.failures,
                        "insight": run.insights,
                        "discovery": run.insights,
                    }.get(str(event.get("type") or ""))
                    if bucket is not None:
                        bucket.append(event)
                save_distillations(run_dir, events)
                previous = ""
                for event in events:
                    related = [previous] if previous else []
                    self.writer.write_event_note(
                        event.to_dict(),
                        run.project_name,
                        run.iteration,
                        related=related,
                    )
                    previous = VaultWriter.event_note_slug(event.to_dict())
                architecture = ""
                if gf_run is not None:
                    architecture = str(
                        (self.kernel._load_architecture(run_dir) or {}).get(
                            "selected", ""
                        )
                    )
                self.writer.write_project_moc(
                    run.project_name,
                    run.original_goal or "",
                    run.status,
                    run.knowledge_events,
                    architecture=architecture,
                )
            except Exception as exc:
                # Distillation is advisory: an LLM/API failure must never
                # break the build loop or the finalize tail.
                self.console.print(
                    f"[yellow]知识蒸馏失败（不影响构建）: {exc}[/yellow]"
                )
                return

        session = None
        flow = None
        try:
            self.kernel._validate_budget_pricing(gf_run.options)
            self.kernel._round_start = gf_run.round_number
            session = GreenfieldGitSession(workspace, gf_run.id)
            if gf_run.run_branch:
                session.resume(gf_run.run_branch)
            else:
                session.start()
                gf_run.base_branch = session.base_branch
                gf_run.base_commit = session.base_commit
                gf_run.run_branch = session.run_branch
            # Clear any stop request left behind by a previous run whenever
            # a run transitions to running; otherwise a user_stop would
            # wedge every subsequent resume at PLAN.
            clear_stop_request(workspace)
            gf_run.status = GreenfieldStatus.RUNNING
            run.status = "running"
            project.status = ProjectStatus.RUNNING
            update_project(project)
            recorder.save_run()
            save_harness_run(run)

            flow = HarnessFlow(event_sink=self._flow_sink(workspace, run))
            contract: AcceptanceContract | None = None
            if not gf_run.slices:
                flow.start_iteration(1)
                flow.transition(HarnessStage.UNDERSTAND)
                contract = UnderstandStage(self.kernel, run.mode).run(
                    gf_run, workspace, recorder, tracker
                )
                run.product_spec = {
                    "mode": run.mode,
                    "acceptance_contract": contract.to_dict(),
                    "repository": self.kernel._repository_summary(workspace),
                }
                if session.repo.is_dirty(untracked_files=True):
                    session.repo.git.add("docs/PRD.md", "docs/ARCHITECTURE.md")
                    session.repo.index.commit(
                        "docs: record acceptance and architecture baseline"
                    )
                research = self.research.run(
                    goal=run.original_goal,
                    acceptance_summary=self._acceptance_summary(contract),
                    architecture_summary=self._architecture_summary(run_dir),
                    iteration=1,
                    run_dir=run_dir,
                    tracker=tracker,
                    mode="auto",
                )
                run.research_reports.append(research.to_dict())
                self._record_research_skip(recorder, research)
                if research.mode == "skipped":
                    recorder.trace(
                        "RESEARCH",
                        f"跳过研究: {research.skip_reason}",
                        "yellow",
                    )
                flow.transition(
                    HarnessStage.RESEARCH,
                    {
                        "mode": research.mode,
                        "skip_reason": research.skip_reason,
                    },
                )
                architecture = self.kernel._load_architecture(run_dir)
                architecture, warnings = self.design.run(
                    research,
                    self._acceptance_summary(contract),
                    architecture,
                    1,
                    tracker,
                )
                run.architecture = dict(architecture)
                for warning in warnings:
                    recorder.trace("DESIGN", f"无效引用已剔除: {warning}", "yellow")
                if research.has_evidence and architecture.get("evidence_citations"):
                    recorder.architecture_decision(architecture)
                flow.transition(
                    HarnessStage.DESIGN,
                    {
                        "architecture": architecture,
                    },
                )
                self.kernel._sanitize_generated_commands(gf_run, contract, recorder)
                self.kernel._normalize_slice_plans(gf_run, contract, recorder)
                self.kernel._write_design_docs(
                    workspace,
                    gf_run,
                    contract,
                    architecture,
                )
                self.kernel._commit_design_docs(session)
            else:
                flow.start_iteration(run.iteration + 1)
                flow.transition(HarnessStage.UNDERSTAND, {"resumed": True})
                flow.transition(HarnessStage.RESEARCH, {"skipped": True})
                flow.transition(HarnessStage.DESIGN, {"resumed": True})
                contract = self.kernel._load_contract(run_dir)
                if contract is None:
                    raise RuntimeError("acceptance contract missing from resumable run")
                run.product_spec = run.product_spec or {
                    "mode": run.mode,
                    "acceptance_contract": contract.to_dict(),
                    "repository": self.kernel._repository_summary(workspace),
                }
                # Resume parity: the kernel applied these plan-consistency
                # steps on every resume; the harness must too, or the
                # persisted plan drifts from the contract.
                self.kernel._sanitize_generated_commands(gf_run, contract, recorder)
                self.kernel._normalize_slice_plans(gf_run, contract, recorder)
                self.kernel._write_design_docs(
                    workspace,
                    gf_run,
                    contract,
                    self.kernel._load_architecture(run_dir),
                )
                self.kernel._commit_design_docs(session)

            while True:
                run.iteration += 1
                flow.start_iteration(run.iteration)
                flow.transition(HarnessStage.PLAN)
                run.work_items = self._greenfield_work_items(gf_run, contract)
                pending = [item for item in run.work_items if item.status == "pending"]
                if stop_requested(workspace):
                    run.stop_state = {
                        "reason": "user_stop",
                        "evidence": self._stop_evidence(run),
                    }
                    break
                if not pending:
                    run.stop_state = {
                        "reason": StopReason.GOALS_SATISFIED.value,
                        "evidence": self._stop_evidence(run),
                    }
                    break

                flow.transition(HarnessStage.BUILD)
                satisfied = self.kernel.build_pending_slices(
                    gf_run,
                    contract,
                    session,
                    recorder,
                    tracker,
                    respect_satisfied_early_exit=(run.iteration == 1),
                    distill=distill_checkpoint,
                )
                run.spent = tracker.spent
                run.work_items = self._greenfield_work_items(gf_run, contract)
                self._sync_candidate_statuses(run)

                flow.transition(
                    HarnessStage.VERIFY,
                    {
                        "hard_gates_passed": satisfied,
                    },
                )
                flow.transition(
                    HarnessStage.REVIEW,
                    {
                        "kernel_review_completed": True,
                    },
                )
                flow.transition(HarnessStage.REFLECT)
                snapshot = ReflectStage().run(
                    gf_run,
                    contract,
                    satisfied,
                    run.iteration,
                    llm=self.llm,
                    review_findings=self._greenfield_review_findings(run_dir),
                    tracker=tracker,
                    track=self.kernel._track,
                )
                run.quality_history.append(snapshot)
                if not satisfied:
                    raise RuntimeError(
                        "hard gates unsatisfied after all work items were built"
                    )
                distill_checkpoint(
                    "round_end",
                    {
                        "iteration": run.iteration,
                        "hard_gates_passed": satisfied,
                    },
                )
                if stop_requested(workspace):
                    run.stop_state = {
                        "reason": StopReason.USER_STOP.value,
                        "evidence": self._stop_evidence(run),
                    }
                    break

                flow.transition(HarnessStage.DISCOVER)
                candidates = self._discover(run, contract, snapshot, tracker)
                flow.transition(HarnessStage.PRIORITIZE)
                backlog, decision = self._prioritize(
                    run,
                    contract,
                    snapshot,
                    candidates,
                    tracker,
                    workspace,
                    require_build_scope=True,
                )
                save_harness_run(run)
                if decision.stop:
                    run.stop_state = {
                        "reason": decision.reason.value,
                        "evidence": decision.evidence,
                    }
                    break
                for index, candidate in enumerate(backlog):
                    candidate.status = "selected"
                    plan = self._candidate_slice(
                        candidate, contract, run.iteration, index
                    )
                    gf_run.slices.append(plan)
                    recorder.save_slice(plan)
                recorder.save_contract(contract)
                run.product_spec["acceptance_contract"] = contract.to_dict()
                self.kernel._sanitize_generated_commands(gf_run, contract, recorder)
                self.kernel._normalize_slice_plans(gf_run, contract, recorder)
                research = self.research.run(
                    goal=run.original_goal,
                    acceptance_summary=self._acceptance_summary(contract),
                    architecture_summary=self._architecture_summary(run_dir),
                    iteration=run.iteration,
                    run_dir=run_dir,
                    tracker=tracker,
                    mode=self._research_mode(backlog),
                )
                run.research_reports.append(research.to_dict())
                self._record_research_skip(recorder, research)
                flow.transition(
                    HarnessStage.RESEARCH,
                    {
                        "mode": research.mode,
                        "skip_reason": research.skip_reason,
                    },
                )
                if research.has_evidence:
                    architecture, warnings = self.design.run(
                        research,
                        self._acceptance_summary(contract),
                        self.kernel._load_architecture(run_dir),
                        run.iteration,
                        tracker,
                    )
                    for warning in warnings:
                        recorder.trace("DESIGN", f"无效引用已剔除: {warning}", "yellow")
                    recorder.architecture_decision(architecture)
                    run.architecture = dict(architecture)
                    self.kernel._write_design_docs(
                        workspace, gf_run, contract, architecture
                    )
                    # In-loop design docs carry evidence from this round;
                    # commit them like the first-run and resume paths so a
                    # pause/resume never meets a dirty tracked tree.
                    # In-loop design docs carry evidence from this round;
                    # commit them like the first-run and resume paths so a
                    # pause/resume never meets a dirty tracked tree.
                    self.kernel._commit_design_docs(session)
                flow.transition(HarnessStage.DESIGN, {"incremental": True})
                save_harness_run(run)

            if run.stop_state.get("reason") == StopReason.USER_STOP.value and not (
                contract is not None and contract.required_complete
            ):
                # The user asked to stop before the contract is satisfied;
                # running the finalize tail would fail the gates and turn a
                # graceful stop into a failed project. Park the run instead.
                flow.transition(
                    HarnessStage.STOP,
                    {
                        "reason": StopReason.USER_STOP.value,
                        **run.stop_state["evidence"],
                    },
                )
                run.status = "stopped"
                run.ended_at = datetime.now(timezone.utc).isoformat()
                run.spent = tracker.spent
                recorder.save_run()
                save_harness_run(run)
                project.status = ProjectStatus.PAUSED
                project.current_stage = "stop"
                project.touch()
                update_project(project)
                self.console.print(
                    f"[bold yellow]STOPPED [USER_REQUEST][/bold yellow]\n"
                    f"运行已按用户请求停止；执行 onep run {project.name} 可随时继续\n"
                    f"记录: {run_dir}"
                )
                return True

            mandatory = self.kernel._final_gate_commands(workspace, gf_run, contract)
            self.kernel._final_verify(
                gf_run,
                contract,
                session,
                mandatory,
                GreenfieldGateRunner(load_config().pipeline.test_timeout),
                recorder,
                tracker,
                distill=distill_checkpoint,
            )
            flow.transition(
                HarnessStage.STOP,
                {
                    "reason": run.stop_state.get("reason", ""),
                    **dict(run.stop_state.get("evidence") or {}),
                },
            )
            summary = self.kernel._write_completion_docs(
                gf_run, contract, session.workspace, mandatory
            )
            documentation_commit = self.kernel._commit_completion_docs(session)
            gf_run.stage = GreenfieldStage.FINISHED
            gf_run.status = GreenfieldStatus.COMPLETED
            gf_run.ended_at = datetime.now(timezone.utc).isoformat()
            gf_run.spent = tracker.spent
            run.status = "completed"
            run.stage = "stop"
            run.ended_at = datetime.now(timezone.utc).isoformat()
            run.spent = tracker.spent
            self._distill_at_completion(run, tracker)
            recorder.trace("FINISHED", "Harness 闭环完成", "green")
            recorder.save_report(self.kernel._report(gf_run, contract))
            recorder.save_run()
            save_harness_run(run)
            project.status = ProjectStatus.COMPLETED
            project.current_stage = ""
            project.touch()
            update_project(project)
            self.console.print(
                f"[bold green]{summary}[/bold green]\n"
                f"[green]Stop: {run.stop_state.get('reason')}[/green]\n"
                f"[green]Greenfield branch: {gf_run.run_branch}[/green]\n"
                f"[dim]Documentation commit: {documentation_commit[:8]}[/dim]\n"
                f"[dim]Run records: {run_dir}[/dim]"
            )
            return True
        except GreenfieldBlocked as exc:
            run.status = "blocked"
            run.stop_state = self._failed_stop_state(run, exc, "blocked")
            if flow is not None:
                flow.fail(str(exc))
            run.stage = "failed"
            save_harness_run(run)
            return self.kernel._block(project, gf_run, recorder, str(exc))
        except KeyboardInterrupt:
            if session is not None:
                session.rollback_attempt()
            run.status = "cancelled"
            run.stop_state = self._failed_stop_state(run, "Run cancelled", "cancelled")
            if flow is not None:
                flow.cancel()
            run.stage = "cancelled"
            save_harness_run(run)
            return self.kernel._fail(
                project, gf_run, recorder, "cancelled", "Run cancelled"
            )
        except Exception as exc:
            if session is not None:
                session.rollback_attempt()
            run.status = "failed"
            run.stop_state = self._failed_stop_state(run, exc, "error")
            if flow is not None:
                flow.fail(str(exc))
            run.stage = "failed"
            save_harness_run(run)
            return self.kernel._fail(
                project,
                gf_run,
                recorder,
                self.kernel._failure_type(exc),
                str(exc),
            )

    def _run_brownfield(
        self,
        project: Project,
        run: HarnessRun,
        workspace: Path,
        options: GreenfieldOptions | None,
    ) -> bool:
        """Brownfield loop: scan UNDERSTAND -> candidate BUILD -> Product
        Loop. Greenfield and brownfield share REFLECT/DISCOVER/PRIORITIZE."""
        from onep.strategy.optimize_models import PlanCandidate

        run_dir = workspace / ".onep" / "optimize" / "runs" / run.id
        tracker = CostTracker(run.options.max_cost)
        from onep.strategy.optimize_models import RunRecord, RunStatus
        from onep.strategy.optimize_recorder import OptimizeRunRecorder

        run_record = RunRecord(
            id=run.id,
            project_name=run.project_name,
            source_path=workspace,
            status=RunStatus.RUNNING,
            budget=run.options.max_cost,
        )
        optimize_recorder = OptimizeRunRecorder(run_dir, run_record)
        optimize_recorder.record_event(
            "harness_run_started",
            {
                "mode": run.mode,
                "workspace": str(workspace),
            },
        )
        commands = list(run.options.test_commands) or list(
            discover_required_test_commands(workspace)
        )
        if not commands:
            run.status = "failed"
            optimize_recorder.record_event(
                "harness_run_completed",
                {
                    "status": "no_commands",
                    "stop_reason": run.stop_state.get("reason", ""),
                    "iteration": run.iteration,
                },
            )
            save_harness_run(run)
            self.console.print(
                "[red]brownfield 需要测试命令[/red]：提供 --test-command 或 "
                "项目清单（pyproject.toml / pytest.ini / package.json 等）"
            )
            return False
        run.status = "running"
        project.status = ProjectStatus.RUNNING
        update_project(project)
        save_harness_run(run)
        flow = HarnessFlow(event_sink=self._flow_sink(workspace, run))
        # Clear any stop request left behind by a previous run; otherwise a
        # stale flag would wedge every brownfield run at PLAN -> USER_STOP
        # (parity with the greenfield path's clear_stop_request).
        clear_stop_request(workspace)
        try:
            flow.start_iteration(1)
            flow.transition(HarnessStage.UNDERSTAND)
            candidates, plans = BrownfieldUnderstandStage(
                self.llm,
                analyzer=analyze_source,
                planner=generate_optimize_plan,
            ).run(
                workspace,
                run.project_name,
                tuple(commands),
                tracker=tracker,
            )
            run.work_items = [
                CandidateAdapter.to_work_item(candidate) for candidate in candidates
            ]
            run.work_item_plans = dict(plans)
            run.product_spec = {
                "mode": run.mode,
                "repository": self.kernel._repository_summary(workspace),
                "current_work_items": [item.to_dict() for item in run.work_items],
            }
            if not run.work_items:
                flow.transition(HarnessStage.PLAN, {"work_items": 0})
                flow.transition(HarnessStage.BUILD, {"skipped": "no work items"})
                tests = PlanTestRunner(load_config().pipeline.test_timeout).run(
                    workspace, commands
                )
                flow.transition(
                    HarnessStage.VERIFY,
                    {"hard_gates_passed": tests.passed},
                )
                review = ReviewAgent(self.llm).review(
                    "Verify the existing repository before declaring no work remains.",
                    "",
                    self.kernel._test_summary(tests),
                    self.kernel._repository_summary(workspace),
                )
                self.kernel._track(tracker, "code_reviewer")
                findings = [
                    str(issue.get("message") or "")
                    for issue in review.blocking_issues
                    if issue.get("message")
                ]
                flow.transition(
                    HarnessStage.REVIEW,
                    {"kernel_review_completed": True, "blocker_count": len(findings)},
                )
                flow.transition(HarnessStage.REFLECT)
                contract = AcceptanceContract(
                    [
                        AcceptanceItem(
                            id="CURRENT-STATE",
                            priority="P0",
                            behavior="Existing repository passes its required gates",
                            status=(
                                "passed"
                                if tests.passed and review.passed
                                else "pending"
                            ),
                        )
                    ]
                )
                snapshot = ReflectStage().run(
                    None,
                    contract,
                    tests.passed and review.passed,
                    0,
                    llm=self.llm,
                    review_findings=findings,
                    tracker=tracker,
                    track=self.kernel._track,
                )
                run.quality_history.append(snapshot)
                if not tests.passed or not review.passed:
                    detail = findings or [
                        next(
                            (
                                result.stderr or result.stdout
                                for result in tests.commands
                                if not result.passed
                            ),
                            "required repository gates failed",
                        )
                    ]
                    raise RuntimeError("; ".join(detail))
                run.stop_state = {
                    "reason": StopReason.GOALS_SATISFIED.value,
                    "evidence": self._stop_evidence(
                        run, note="scan found no optimization opportunities"
                    ),
                }
                flow.transition(
                    HarnessStage.STOP,
                    {
                        "reason": StopReason.GOALS_SATISFIED.value,
                        **run.stop_state["evidence"],
                    },
                )
                self._complete_brownfield(project, run, tracker, optimize_recorder)
                return True

            contract = self._synthesized_contract(run.work_items)
            research = self.research.run(
                goal=run.original_goal,
                acceptance_summary=self._acceptance_summary(contract),
                architecture_summary=json.dumps(
                    run.architecture or {}, ensure_ascii=False
                ),
                iteration=1,
                run_dir=run_dir,
                tracker=tracker,
                mode="auto",
            )
            run.research_reports.append(research.to_dict())
            self._record_research_skip(optimize_recorder, research)
            flow.transition(
                HarnessStage.RESEARCH,
                {
                    "mode": research.mode,
                    "skip_reason": research.skip_reason,
                },
            )
            run.architecture, _ = self.design.run(
                research,
                self._acceptance_summary(contract),
                run.architecture or {"selected": "existing repository architecture"},
                1,
                tracker,
            )
            flow.transition(
                HarnessStage.DESIGN,
                {
                    "architecture": run.architecture,
                },
            )

            build = BrownfieldBuildStage(
                workspace,
                run_dir,
                run.id,
                self.llm,
                tracker=tracker,
                recorder=optimize_recorder,
            )
            while True:
                run.iteration += 1
                flow.start_iteration(run.iteration)
                flow.transition(HarnessStage.PLAN)
                if stop_requested(workspace):
                    run.stop_state = {
                        "reason": StopReason.USER_STOP.value,
                        "evidence": self._stop_evidence(run),
                    }
                    break
                pending = [item for item in run.work_items if item.status == "pending"]
                if not pending:
                    failed = [
                        item.id for item in run.work_items if item.status != "completed"
                    ]
                    if failed:
                        raise RuntimeError(
                            "work items did not complete: " + ", ".join(failed)
                        )
                    run.stop_state = {
                        "reason": StopReason.GOALS_SATISFIED.value,
                        "evidence": self._stop_evidence(run),
                    }
                    break

                flow.transition(HarnessStage.BUILD)
                result = build.build(pending, run.work_item_plans, commands)
                by_id = {item.id: item for item in result["items"]}
                for item in run.work_items:
                    if item.id in by_id:
                        updated = by_id[item.id]
                        item.status = updated.status
                        item.attempts = updated.attempts
                        item.commit_sha = updated.commit_sha
                run.spent = tracker.spent

                self._sync_candidate_statuses(run)
                flow.transition(
                    HarnessStage.VERIFY,
                    {
                        "hard_gates_passed": result["integration_passed"],
                    },
                )
                flow.transition(
                    HarnessStage.REVIEW,
                    {
                        "kernel_review_completed": True,
                    },
                )
                flow.transition(HarnessStage.REFLECT)
                contract = self._synthesized_contract(run.work_items)
                snapshot = ReflectStage().run(
                    None,
                    contract,
                    result["integration_passed"],
                    run.iteration,
                    llm=self.llm,
                    review_findings=self._brownfield_review_findings(result["records"]),
                    tracker=tracker,
                    track=self.kernel._track,
                )
                run.quality_history.append(snapshot)
                if not result["integration_passed"]:
                    raise RuntimeError(
                        "brownfield hard gates unsatisfied after build round"
                    )
                optimize_recorder.record_event(
                    "round_end",
                    {
                        "iteration": run.iteration,
                        "integration_passed": result["integration_passed"],
                        "items": [item.to_dict() for item in run.work_items],
                    },
                )
                self._distill_brownfield_round(
                    run, run_dir, tracker, result["integration_passed"]
                )
                if stop_requested(workspace):
                    run.stop_state = {
                        "reason": StopReason.USER_STOP.value,
                        "evidence": self._stop_evidence(run),
                    }
                    break

                flow.transition(HarnessStage.DISCOVER)
                candidates = self._discover(run, contract, snapshot, tracker)
                flow.transition(HarnessStage.PRIORITIZE)
                backlog, decision = self._prioritize(
                    run, contract, snapshot, candidates, tracker, workspace
                )
                save_harness_run(run)
                if decision.stop:
                    run.stop_state = {
                        "reason": decision.reason.value,
                        "evidence": decision.evidence,
                    }
                    break
                for index, candidate in enumerate(backlog):
                    try:
                        generated = self._plan_for(candidate, workspace, index)
                    except Exception as exc:
                        candidate.status = "parked"
                        self.console.print(
                            f"[yellow]Plan 生成失败，候选退回候选池: "
                            f"{candidate.title}: {exc}[/yellow]"
                        )
                        continue
                    candidate.status = "selected"
                    probe = PlanCandidate(
                        id=f"iter{run.iteration}-{index + 1}",
                        title=candidate.title,
                        summary=candidate.description,
                        files={
                            Path(path)
                            for path in getattr(generated, "expected_files", ())
                        },
                        focused_test_commands=tuple(
                            getattr(generated, "test_commands", ())
                        ),
                        fingerprint=candidate.fingerprint,
                    )
                    item = CandidateAdapter.to_work_item(probe)
                    candidate.work_item_id = item.id
                    run.work_items.append(item)
                    run.work_item_plans[item.id] = generated.plan_markdown
                research = self.research.run(
                    goal=run.original_goal or "(pure code optimization)",
                    acceptance_summary=self._acceptance_summary(contract),
                    architecture_summary=json.dumps(
                        run.architecture or {}, ensure_ascii=False
                    ),
                    iteration=run.iteration,
                    run_dir=run_dir,
                    tracker=tracker,
                    mode=self._research_mode(backlog),
                )
                run.research_reports.append(research.to_dict())
                self._record_research_skip(optimize_recorder, research)
                flow.transition(
                    HarnessStage.RESEARCH,
                    {
                        "mode": research.mode,
                        "skip_reason": research.skip_reason,
                        "brownfield": True,
                    },
                )
                if research.has_evidence:
                    run.architecture, _ = self.design.run(
                        research,
                        self._acceptance_summary(contract),
                        run.architecture,
                        run.iteration,
                        tracker,
                    )
                flow.transition(
                    HarnessStage.DESIGN,
                    {
                        "incremental": True,
                        "architecture": run.architecture,
                    },
                )
                save_harness_run(run)

            flow.transition(
                HarnessStage.STOP,
                {
                    "reason": run.stop_state.get("reason", ""),
                    **dict(run.stop_state.get("evidence") or {}),
                },
            )
            self._complete_brownfield(project, run, tracker, optimize_recorder)
            return True
        except Exception as exc:
            run.status = "failed"
            flow.fail(str(exc))
            run.stage = "failed"
            run.stop_state = {
                "reason": "error",
                "evidence": {"error": str(exc)},
            }
            optimize_recorder.record_event(
                "harness_run_completed",
                {
                    "status": "failed",
                    "stop_reason": run.stop_state.get("reason", ""),
                    "iteration": run.iteration,
                },
            )
            save_harness_run(run)
            project.status = ProjectStatus.FAILED
            update_project(project)
            self.console.print(f"[red]brownfield 运行失败: {exc}[/red]")
            return False

    def _complete_brownfield(
        self,
        project,
        run,
        tracker,
        optimize_recorder=None,
    ) -> None:
        run.stage = "stop"
        run.status = "completed"
        run.ended_at = datetime.now(timezone.utc).isoformat()
        run.spent = tracker.spent
        self._distill_at_completion(run, tracker)
        if optimize_recorder is not None:
            optimize_recorder.record_event(
                "harness_run_completed",
                {
                    "status": run.status,
                    "stop_reason": run.stop_state.get("reason", ""),
                    "iteration": run.iteration,
                },
            )
        save_harness_run(run)
        project.status = ProjectStatus.COMPLETED
        project.current_stage = ""
        project.touch()
        update_project(project)
        self.console.print(
            f"[bold green]Brownfield 闭环完成[/bold green]\n"
            f"[green]Stop: {run.stop_state.get('reason')}[/green]\n"
            f"[dim]Iterations: {run.iteration}[/dim]"
        )

    def _distill_at_completion(self, run: HarnessRun, tracker) -> None:
        try:
            self.writer.project_root = project_vault_root(Path(run.workspace))
            self.writer.write_project_moc(
                run.project_name,
                run.original_goal,
                run.status,
                run.knowledge_events,
                architecture=str(run.architecture.get("selected") or ""),
            )
            generalizable = [
                event for event in run.knowledge_events if event.get("generalizable")
            ]
            if not generalizable:
                return
            cross = CrossProjectDistiller(
                self.llm, self.writer, track=self.kernel._track
            )
            cross.run(generalizable, run.project_name, run.original_goal, tracker)
        except Exception as exc:
            # Completion distillation is advisory: an LLM/API failure must
            # never mark a fully-passed run as failed.
            self.console.print(
                f"[yellow]跨项目知识蒸馏失败（不影响完成）: {exc}[/yellow]"
            )
            return

    def _distill_brownfield_round(
        self,
        run: HarnessRun,
        run_dir: Path,
        tracker,
        hard_gates_passed: bool,
    ) -> None:
        """Apply the same Knowledge Loop to brownfield recorder events."""
        try:
            all_events = list(load_run_events(run_dir))
            raw = all_events[run.knowledge_cursor :]
            next_knowledge_cursor = len(all_events)
            raw.append(
                {
                    "type": "round_end",
                    "iteration": run.iteration,
                    "hard_gates_passed": hard_gates_passed,
                }
            )
            events = self.knowledge.distill(
                raw,
                "round_end",
                run.iteration,
                context=(
                    f"project: {run.project_name}\n"
                    f"goal: {run.original_goal or '(none)'}"
                ),
                tracker=tracker,
                collapse=True,
            )
            run.knowledge_cursor = next_knowledge_cursor
            if not events:
                return
            distilled = [event.to_dict() for event in events]
            run.knowledge_events.extend(distilled)
            for event in distilled:
                bucket = {
                    "decision": run.decisions,
                    "experiment": run.experiments,
                    "failure": run.failures,
                    "insight": run.insights,
                    "discovery": run.insights,
                }.get(str(event.get("type") or ""))
                if bucket is not None:
                    bucket.append(event)
            save_distillations(run_dir, events)
            self.writer.project_root = project_vault_root(Path(run.workspace))
            previous = ""
            for event in distilled:
                related = [previous] if previous else []
                self.writer.write_event_note(
                    event, run.project_name, run.iteration, related=related
                )
                previous = VaultWriter.event_note_slug(event)
            self.writer.write_project_moc(
                run.project_name,
                run.original_goal,
                run.status,
                run.knowledge_events,
                architecture=str(run.architecture.get("selected") or ""),
            )
        except Exception as exc:
            self.console.print(f"[yellow]知识蒸馏失败（不影响构建）: {exc}[/yellow]")

    @staticmethod
    def _sync_candidate_statuses(run: HarnessRun) -> None:
        by_id = {item.id: item for item in run.work_items}
        for candidate in run.improvement_candidates:
            if not candidate.work_item_id:
                continue
            item = by_id.get(candidate.work_item_id)
            if item is None:
                continue
            if item.status == "completed":
                candidate.status = "integrated"
            elif item.status == "failed":
                candidate.status = "failed"

    @staticmethod
    def _merge_improvement_candidates(run, backlog, parked) -> None:
        """Persist the candidate pool instead of replacing it each round."""
        positions = {
            candidate.id: index
            for index, candidate in enumerate(run.improvement_candidates)
        }
        for candidate in [*backlog, *parked]:
            position = positions.get(candidate.id)
            if position is None:
                positions[candidate.id] = len(run.improvement_candidates)
                run.improvement_candidates.append(candidate)
                continue
            existing = run.improvement_candidates[position]
            if existing.status == "integrated":
                continue
            run.improvement_candidates[position] = candidate

    def _discover(self, run, contract, snapshot, tracker):
        return BrainstormStage(self.llm, track=self.kernel._track).run(
            goal=run.original_goal or "(pure code optimization)",
            acceptance_summary=self._acceptance_summary(contract),
            iteration=run.iteration,
            snapshot=snapshot,
            tracker=tracker,
            code_signals=self._code_signals(run),
            prior_titles=tuple(
                candidate.title for candidate in run.improvement_candidates
            ),
        )

    def _prioritize(
        self,
        run,
        contract,
        snapshot,
        candidates,
        tracker,
        workspace,
        require_build_scope=False,
    ):
        scored = self.scorer.score_candidates(
            candidates,
            run.original_goal or "(pure code optimization)",
            self._acceptance_summary(contract),
            run.iteration,
            tracker,
        )
        backlog, parked = PrioritizeStage().run(
            scored,
            integrated_fingerprints=self._integrated_fingerprints(run),
            use_scores=True,
        )
        self._merge_improvement_candidates(run, backlog, parked)
        backlog, parked = apply_candidate_decisions(run, workspace, backlog, parked)
        if require_build_scope:
            backlog = self._park_unbuildable_greenfield_candidates(backlog)
        return backlog, evaluate_stop(run, snapshot, backlog, scored=scored)

    @staticmethod
    def _candidate_slice(
        candidate,
        contract: AcceptanceContract,
        iteration: int,
        index: int,
    ):
        plan = candidate_to_slice(candidate, iteration, index)
        criteria = candidate.acceptance_criteria or [candidate.description]
        acceptance_ids = []
        for criterion_index, criterion in enumerate(criteria, 1):
            if not str(criterion).strip():
                continue
            acceptance_id = f"IMP-{iteration}-{index + 1}-{criterion_index}"
            acceptance_ids.append(acceptance_id)
            contract.items.append(
                AcceptanceItem(
                    id=acceptance_id,
                    priority="P1",
                    behavior=str(criterion),
                    commands=list(candidate.focused_commands),
                )
            )
        plan.acceptance_ids = acceptance_ids
        return plan

    @staticmethod
    def _synthesized_contract(items) -> AcceptanceContract:
        """Brownfield REFLECT anchor: each WorkItem is an acceptance item."""
        return AcceptanceContract(
            [
                AcceptanceItem(
                    id=item.id,
                    priority="P0",
                    behavior=item.objective,
                    status="passed" if item.status == "completed" else "pending",
                )
                for item in items
            ]
        )

    @staticmethod
    def _greenfield_work_items(gf_run, contract) -> list:
        criteria = {item.id: item.behavior for item in contract.items}
        work_items = [SliceAdapter.to_work_item(plan) for plan in gf_run.slices]
        for item in work_items:
            item.acceptance_criteria = [
                criteria[item_id]
                for item_id in item.acceptance_ids
                if item_id in criteria
            ]
        return work_items

    @staticmethod
    def _code_signals(run: HarnessRun) -> str:
        lines = []
        for item in run.work_items:
            lines.append(f"- {item.id} [{item.status}] attempts={item.attempts}")
        if run.quality_history:
            latest = run.quality_history[-1]
            lines.append(
                f"- quality={latest.quality_score:.4f} "
                f"blockers={latest.blocker_count} risks={'; '.join(latest.risks) or 'none'}"
            )
        for failure in run.failures[-3:]:
            lines.append(
                f"- failure: {failure.get('problem') or failure.get('reason') or 'unknown'}"
            )
        return "\n".join(lines) or "(none)"

    @staticmethod
    def _greenfield_review_findings(run_dir: Path) -> list[str]:
        findings = []
        for path in (Path(run_dir) / "slices").glob("*/review.json"):
            try:
                review = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            findings.extend(str(value) for value in review.get("findings") or [])
        return findings

    @staticmethod
    def _research_mode(candidates) -> str:
        """Escalate only architecture-sized rounds to external research."""
        keywords = (
            "architecture",
            "framework",
            "database",
            "storage",
            "migration",
            "refactor",
        )
        for candidate in candidates:
            text = f"{candidate.title} {candidate.description}".casefold()
            roots = {
                Path(path).parts[0]
                for path in candidate.expected_files
                if Path(path).parts
            }
            if any(word in text for word in keywords) or len(roots) >= 2:
                return "full"
        return "lightweight"

    @staticmethod
    def _record_research_skip(recorder, report) -> None:
        if report.mode != "skipped":
            return
        payload = {"reason": report.skip_reason}
        if hasattr(recorder, "event"):
            recorder.event("research_skipped", payload)
        else:
            recorder.record_event("research_skipped", payload)

    @staticmethod
    def _brownfield_review_findings(records) -> list[str]:
        findings = []
        for record in records:
            for attempt in getattr(record, "attempts", ()):
                review = getattr(attempt, "review", None)
                if review is None:
                    continue
                findings.extend(
                    str(issue.get("message") or "")
                    for issue in review.blocking_issues
                    if issue.get("message")
                )
        return findings

    @staticmethod
    def _stop_evidence(run: HarnessRun, **extra) -> dict:
        """Small, consistent audit payload for every terminal decision."""
        evidence = {
            "iteration": run.iteration,
            "quality_curve": [
                round(snapshot.quality_score, 4)
                for snapshot in run.quality_history[-3:]
            ],
            "score_distribution": {
                candidate.id: candidate.score
                for candidate in run.improvement_candidates
                if candidate.score is not None
            },
        }
        evidence.update(extra)
        return evidence

    @staticmethod
    def _failed_stop_state(run: HarnessRun, error, reason: str) -> dict:
        proposed = str((run.stop_state or {}).get("reason") or "")
        evidence = HarnessEngine._stop_evidence(run, error=str(error))
        if proposed:
            evidence["rejected_stop_reason"] = proposed
        return {"reason": reason, "evidence": evidence}

    def _plan_for(self, candidate, workspace: Path, index: int):
        item = StrategyItem(
            id=candidate.id,
            title=candidate.title,
            file_location="unknown",
            summary=candidate.description,
        )
        return generate_optimize_plan(item, workspace, self.llm, plan_index=index + 1)

    @staticmethod
    def _park_unbuildable_greenfield_candidates(candidates):
        """Keep incomplete brainstorm output out of the strict BUILD gate.

        Greenfield improvement work has no later planner to infer a safe file
        scope. A candidate therefore needs observable acceptance criteria and
        an explicit file boundary before it can become a SlicePlan.
        """
        ready = []
        for candidate in candidates:
            if candidate.acceptance_criteria and candidate.expected_files:
                ready.append(candidate)
                continue
            candidate.status = "parked"
            candidate.dimensions = {
                **candidate.dimensions,
                "planning_status": "missing acceptance_criteria or expected_files",
            }
        return ready

    @staticmethod
    def _acceptance_summary(contract: AcceptanceContract) -> str:
        return "\n".join(
            f"- {item.id} [{item.priority}] {item.behavior} ({item.status})"
            for item in contract.items
        )

    @staticmethod
    def _architecture_summary(run_dir: Path) -> str:
        import json
        from onep.greenfield.engine import GreenfieldEngine

        architecture = GreenfieldEngine._load_architecture(run_dir)
        return json.dumps(architecture, ensure_ascii=False, indent=2)

    @staticmethod
    def _adopt_legacy_run(workspace: Path) -> GreenfieldRun | None:
        """Adopt an in-flight kernel-era greenfield run, if one exists.

        Projects created before the harness lands persist their greenfield
        run id in .onep/state.yaml (artifacts.greenfield_run_id) and commit
        work on onep/greenfield-* branches. Resume that run instead of
        silently restarting discovery and stranding the committed work.
        """
        state = load_state(workspace)
        run_id = state.artifacts.get("greenfield_run_id")
        if not run_id:
            return None
        return GreenfieldRecorder.load(
            workspace / ".onep" / "greenfield" / "runs" / run_id / "run.yaml"
        )

    @staticmethod
    def _integrated_fingerprints(run: HarnessRun) -> set[str]:
        candidate_fingerprints = {
            candidate.fingerprint
            for candidate in run.improvement_candidates
            if candidate.status == "integrated" and candidate.fingerprint
        }
        work_item_fingerprints = {
            item.fingerprint
            for item in run.work_items
            if item.status == "completed" and item.fingerprint
        }
        return candidate_fingerprints | work_item_fingerprints

    @staticmethod
    def _flow_sink(workspace: Path, run: HarnessRun | None = None):
        """Best-effort append-only sink for flow transitions (web console)."""
        path = Path(workspace) / ".onep" / "harness" / "flow-events.jsonl"

        def sink(event_type: str, payload: dict) -> None:
            try:
                if run is not None:
                    run.stage = str(payload.get("stage") or run.stage)
                    save_harness_run(run)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {"type": event_type, "payload": payload}, ensure_ascii=False
                        )
                        + "\n"
                    )
            except OSError:
                pass  # observability is best-effort; never break the loop

        return sink
