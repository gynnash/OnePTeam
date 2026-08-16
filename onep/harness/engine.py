"""Harness engine — orchestrates the unified autonomous development loop."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from rich.console import Console

from onep.config import load_config
from onep.greenfield.engine import GreenfieldBlocked, GreenfieldEngine
from onep.greenfield.gates import GreenfieldGateRunner
from onep.greenfield.git_session import GreenfieldGitSession
from onep.greenfield.models import (
    AcceptanceContract,
    GreenfieldOptions,
    GreenfieldRun,
    GreenfieldStage,
    GreenfieldStatus,
)
from onep.greenfield.recorder import GreenfieldRecorder
from onep.harness.discover import BrainstormStage, PrioritizeStage
from onep.harness.models import (
    HarnessOptions,
    HarnessRun,
    SliceAdapter,
    candidate_to_slice,
)
from onep.harness.persistence import (
    clear_stop_request,
    load_harness_run,
    save_harness_run,
    stop_requested,
)
from onep.harness.reflect import ReflectStage, evaluate_stop
from onep.harness.states import HarnessFlow, HarnessStage
from onep.harness.understand import HarnessUnsupportedMode, UnderstandStage
from onep.llm.adapters import LLMAdapter
from onep.llm.cost import CostTracker
from onep.persistence.database import update_project
from onep.persistence.models import Project, ProjectMode, ProjectStatus


class HarnessEngine:
    """Top-level orchestrator: Product Loop around the Execution Kernel."""

    def __init__(self, console: Console | None = None, llm=None):
        self.console = console or Console()
        self.llm = llm or LLMAdapter()
        self.kernel = GreenfieldEngine(self.console, self.llm)

    def run(
        self,
        project: Project,
        options: GreenfieldOptions | None = None,
    ) -> bool:
        workspace = Path(project.workspace_path).resolve()
        run = load_harness_run(workspace)
        if run is None:
            mode = (
                "greenfield"
                if project.mode == ProjectMode.GREENFIELD
                else "brownfield"
            )
            run = HarnessRun(
                id=f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
                project_name=project.name,
                workspace=str(workspace),
                mode=mode,
                original_goal=project.requirement,
                options=HarnessOptions.from_greenfield(
                    options or GreenfieldOptions()
                ),
            )
            clear_stop_request(workspace)
            save_harness_run(run)
        elif options is not None:
            run.options = HarnessOptions.from_greenfield(options)
        if run.mode != "greenfield":
            raise HarnessUnsupportedMode(
                "Brownfield harness unification lands in P2; "
                "use `onep optimize` meanwhile."
            )

        gf_run = run.greenfield_run
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
        session = None
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
            gf_run.status = GreenfieldStatus.RUNNING
            run.status = "running"
            project.status = ProjectStatus.RUNNING
            update_project(project)
            recorder.save_run()
            save_harness_run(run)

            flow = HarnessFlow()
            contract: AcceptanceContract | None = None
            if not gf_run.slices:
                flow.start_iteration(1)
                flow.transition(HarnessStage.UNDERSTAND)
                contract = UnderstandStage(self.kernel, run.mode).run(
                    gf_run, workspace, recorder, tracker
                )
                if session.repo.is_dirty(untracked_files=True):
                    session.repo.git.add(
                        "docs/PRD.md", "docs/ARCHITECTURE.md"
                    )
                    session.repo.index.commit(
                        "docs: record acceptance and architecture baseline"
                    )
                flow.transition(HarnessStage.RESEARCH, {
                    "skipped": True,
                    "reason": "research stage arrives in P2",
                })
                flow.transition(HarnessStage.DESIGN, {
                    "architecture": self.kernel._load_architecture(run_dir),
                })
                self.kernel._sanitize_generated_commands(
                    gf_run, contract, recorder
                )
                self.kernel._normalize_slice_plans(
                    gf_run, contract, recorder
                )
                self.kernel._write_design_docs(
                    workspace, gf_run, contract,
                    self.kernel._load_architecture(run_dir),
                )
                self.kernel._commit_design_docs(session)
            else:
                flow.start_iteration(run.iteration + 1)
                flow.transition(HarnessStage.UNDERSTAND, {"resumed": True})
                flow.transition(HarnessStage.RESEARCH, {"skipped": True})
                flow.transition(HarnessStage.DESIGN, {"resumed": True})
                contract = self.kernel._load_contract(run_dir)
                if contract is None:
                    raise RuntimeError(
                        "acceptance contract missing from resumable run"
                    )

            while True:
                run.iteration += 1
                flow.start_iteration(run.iteration)
                flow.transition(HarnessStage.PLAN)
                run.work_items = [
                    SliceAdapter.to_work_item(plan) for plan in gf_run.slices
                ]
                pending = [
                    item for item in run.work_items
                    if item.status == "pending"
                ]
                if stop_requested(workspace):
                    run.stop_state = {
                        "reason": "user_stop", "evidence": {"iteration": run.iteration},
                    }
                    flow.transition(HarnessStage.STOP, {
                        "reason": "user_stop"
                    })
                    break
                if not pending:
                    run.stop_state = {
                        "reason": "no_pending_work",
                        "evidence": {"iteration": run.iteration},
                    }
                    flow.transition(HarnessStage.STOP, {
                        "reason": "no_pending_work"
                    })
                    break

                flow.transition(HarnessStage.BUILD)
                satisfied = self.kernel.build_pending_slices(
                    gf_run, contract, session, recorder, tracker,
                    respect_satisfied_early_exit=(run.iteration == 1),
                )
                run.spent = tracker.spent
                run.work_items = [
                    SliceAdapter.to_work_item(plan) for plan in gf_run.slices
                ]

                flow.transition(HarnessStage.REFLECT)
                snapshot = ReflectStage().run(
                    gf_run, contract, satisfied, run.iteration
                )
                run.quality_history.append(snapshot)
                if not satisfied:
                    raise RuntimeError(
                        "hard gates unsatisfied after all work items were built"
                    )

                flow.transition(HarnessStage.DISCOVER)
                candidates = BrainstormStage(
                    self.llm, track=self.kernel._track
                ).run(
                    goal=run.original_goal,
                    acceptance_summary=self._acceptance_summary(contract),
                    iteration=run.iteration,
                    snapshot=snapshot,
                    tracker=tracker,
                )

                flow.transition(HarnessStage.PRIORITIZE)
                backlog, parked = PrioritizeStage().run(
                    candidates,
                    integrated_fingerprints=self._integrated_fingerprints(run),
                )
                run.improvement_candidates = [
                    *[c for c in run.improvement_candidates
                       if c.status not in {"parked", "duplicate"}],
                    *backlog,
                    *parked,
                ]
                decision = evaluate_stop(run, snapshot, backlog)
                save_harness_run(run)
                if decision.stop:
                    run.stop_state = {
                        "reason": decision.reason.value,
                        "evidence": decision.evidence,
                    }
                    flow.transition(HarnessStage.STOP, {
                        "reason": decision.reason.value,
                        **decision.evidence,
                    })
                    break
                for index, candidate in enumerate(backlog):
                    candidate.status = "integrated"
                    gf_run.slices.append(
                        candidate_to_slice(
                            candidate, run.iteration, index
                        )
                    )
                    recorder.save_slice(gf_run.slices[-1])
                flow.transition(HarnessStage.RESEARCH, {
                    "skipped": True,
                    "reason": "research stage arrives in P2",
                })
                flow.transition(HarnessStage.DESIGN, {"incremental": True})
                save_harness_run(run)

            mandatory = self.kernel._final_gate_commands(
                workspace, gf_run, contract
            )
            self.kernel._final_verify(
                gf_run, contract, session, mandatory,
                GreenfieldGateRunner(load_config().pipeline.test_timeout),
                recorder, tracker,
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
            save_harness_run(run)
            return self.kernel._block(
                project, gf_run, recorder, str(exc)
            )
        except KeyboardInterrupt:
            if session is not None:
                session.rollback_attempt()
            run.status = "cancelled"
            save_harness_run(run)
            return self.kernel._fail(
                project, gf_run, recorder, "cancelled", "Run cancelled"
            )
        except Exception as exc:
            if session is not None:
                session.rollback_attempt()
            run.status = "failed"
            save_harness_run(run)
            return self.kernel._fail(
                project, gf_run, recorder,
                self.kernel._failure_type(exc), str(exc),
            )

    @staticmethod
    def _acceptance_summary(contract: AcceptanceContract) -> str:
        return "\n".join(
            f"- {item.id} [{item.priority}] {item.behavior} ({item.status})"
            for item in contract.items
        )

    @staticmethod
    def _integrated_fingerprints(run: HarnessRun) -> set[str]:
        return {
            candidate.fingerprint
            for candidate in run.improvement_candidates
            if candidate.status == "integrated" and candidate.fingerprint
        }
