"""Coordinate the LLM-led Optimize loop with external safety gates."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import git

from onep.strategy.models import StrategyItem
from onep.strategy.optimize_models import (
    AttemptRecord,
    FailureReason,
    PlanCandidate,
    PlanRecord,
    PlanStatus,
)
from onep.llm.router import resolve_model
from onep.llm.cost import estimate_call_cost
from onep.config import load_config


class OptimizeCoordinator:
    def __init__(
        self,
        engine,
        test_runner,
        reviewer,
        git_session,
        llm=None,
        recorder=None,
        cost_tracker=None,
        max_attempts: int = 3,
        project_context: str = "",
        llm_reservation: float | None = None,
        memory_context: str = "",
    ):
        self.engine = engine
        self.test_runner = test_runner
        self.reviewer = reviewer
        self.git_session = git_session
        self.llm = llm
        self.recorder = recorder
        self.cost_tracker = cost_tracker
        self.max_attempts = max_attempts
        self.project_context = project_context
        self.llm_reservation = llm_reservation
        self.memory_context = memory_context
        self._reservation_prompt = ""
        self._reserved_amount = 0.0

    def develop_plan(
        self, candidate: PlanCandidate, plan_text: str, session=None
    ) -> PlanRecord:
        self._active_record = None
        self._active_session = session
        try:
            return self._develop_plan_impl(candidate, plan_text, session)
        except Exception as exc:
            record = self._active_record or PlanRecord(candidate=candidate)
            session = self._active_session
            if record.status not in {
                PlanStatus.FAILED, PlanStatus.ROLLED_BACK,
                PlanStatus.INTEGRATED, PlanStatus.SKIPPED,
            }:
                try:
                    record.fail(FailureReason.DEVELOPER_FAILED, str(exc))
                except ValueError:
                    record.status = PlanStatus.FAILED
                    record.failure_reason = FailureReason.INTERNAL_ERROR
                    record.failure_detail = str(exc)
            self._safe_rollback(record, plan_text, session)
            return record

    def _develop_plan_impl(
        self, candidate: PlanCandidate, plan_text: str, session=None
    ) -> PlanRecord:
        record = PlanRecord(candidate=candidate)
        self._active_record = record
        self._reservation_prompt = (
            plan_text + self.project_context + self.memory_context
        )
        record.transition_to(PlanStatus.PLAN_READY)
        self._event("plan_generated", record)
        if session is None:
            try:
                session = self.git_session.create_plan_session(
                    candidate.id, candidate.title
                )
            except Exception as exc:
                record.fail(FailureReason.BRANCH_CREATE_FAILED, str(exc))
                return record
        self._active_session = session
        record.transition_to(PlanStatus.BRANCH_CREATED)
        self._event("branch_created", record)
        record.branch = session.branch_name
        record.base_commit = session.base_commit
        if self.recorder:
            self.recorder.save_plan(record, plan_text)
        feedback = ""
        last_reason = FailureReason.FIX_ATTEMPTS_EXHAUSTED

        for number in range(1, self.max_attempts + 1):
            if self.cost_tracker and (
                not self.cost_tracker.can_continue()
                or not self._reserve_budget("optimize_developer")
            ):
                record.fail(FailureReason.BUDGET_EXHAUSTED, "LLM budget exhausted")
                break
            record.transition_to(PlanStatus.DEVELOPING)
            self._event("developer_attempt_started", record, {"attempt": number})
            item = StrategyItem(
                id=candidate.id,
                title=candidate.title,
                file_location=(
                    str(sorted(candidate.files, key=str)[0])
                    if candidate.files else "unknown"
                ),
                summary=candidate.summary,
            )
            try:
                try:
                    result = self.engine.execute_attempt(
                        item=item,
                        source_path=str(session.worktree),
                        workspace=str(session.worktree),
                        llm_adapter=self.llm,
                        feedback=feedback,
                        memory_context=self.memory_context,
                    )
                except Exception as exc:
                    attempt = AttemptRecord(
                        number=number,
                        branch=session.branch_name,
                        base_commit=session.base_commit,
                        feedback=[feedback] if feedback else [],
                        ended_at=datetime.now(timezone.utc).isoformat(),
                        status="developer_failed",
                        artifacts={"developer_error": str(exc)},
                    )
                    record.attempts.append(attempt)
                    self._persist_attempt(record, attempt, plan_text)
                    raise
            finally:
                self._release_budget()
            developer_cost = self._record_cost("optimize_developer")
            changed = session.changed_files()
            attempt = AttemptRecord(
                number=number,
                branch=session.branch_name,
                base_commit=session.base_commit,
                changed_files={Path(path) for path in changed},
                feedback=[feedback] if feedback else [],
                artifacts={"developer_output": result.output},
            )
            if developer_cost:
                attempt.token_usage.append(developer_cost)
                attempt.stage_costs["optimize_developer"] = developer_cost["cost"]
            if not changed:
                feedback = "No files changed."
                last_reason = FailureReason.NO_CHANGES
                attempt.ended_at = datetime.now(timezone.utc).isoformat()
                attempt.status = "no_changes"
                attempt.cost = sum(
                    cost for cost in attempt.stage_costs.values()
                    if cost is not None
                )
                record.attempts.append(attempt)
                self._persist_attempt(record, attempt, plan_text)
                self._event("repair_requested", record, {"attempt": number})
                if number < self.max_attempts:
                    record.transition_to(PlanStatus.TESTING)
                    record.transition_to(PlanStatus.FIXING)
                    continue
                continue

            record.transition_to(PlanStatus.TESTING)
            tests = self.test_runner.run(
                session.worktree, list(candidate.test_commands)
            )
            attempt.test_results = tests.commands
            if not tests.passed:
                last_reason = FailureReason.TEST_FAILED
                attempt.ended_at = datetime.now(timezone.utc).isoformat()
                attempt.status = "test_failed"
                attempt.cost = sum(
                    cost for cost in attempt.stage_costs.values()
                    if cost is not None
                )
                feedback = "\n".join(
                    command.stderr or command.stdout
                    for command in tests.commands if not command.passed
                ) or "Tests failed."
                record.attempts.append(attempt)
                self._persist_attempt(record, attempt, plan_text)
                self._event("tests_completed", record, {
                    "attempt": number, "passed": False,
                })
                if number < self.max_attempts:
                    record.transition_to(PlanStatus.FIXING)
                    self._event("repair_requested", record, {
                        "attempt": number, "reason": "tests",
                    })
                    continue
                break

            record.transition_to(PlanStatus.REVIEWING)
            self._event("tests_completed", record, {
                "attempt": number, "passed": True,
            })
            if self.cost_tracker and not self._reserve_budget("code_reviewer"):
                attempt.test_results = tests.commands
                record.attempts.append(attempt)
                self._persist_attempt(record, attempt, plan_text)
                record.fail(
                    FailureReason.BUDGET_EXHAUSTED,
                    "review budget reservation rejected",
                )
                break
            try:
                review = self.reviewer.review(
                    plan_text,
                    session.diff(),
                    self._test_summary(tests.commands),
                    self.project_context,
                )
            finally:
                self._release_budget()
            reviewer_cost = self._record_cost("code_reviewer")
            attempt.review = review
            if reviewer_cost:
                attempt.token_usage.append(reviewer_cost)
                attempt.stage_costs["code_reviewer"] = reviewer_cost["cost"]
            attempt.ended_at = datetime.now(timezone.utc).isoformat()
            attempt.status = "passed" if review.passed else "review_failed"
            attempt.cost = sum(
                cost for cost in attempt.stage_costs.values()
                if cost is not None
            )
            record.attempts.append(attempt)
            self._persist_attempt(record, attempt, plan_text)
            self._event("review_completed", record, {
                "attempt": number, "passed": review.passed,
            })
            if not review.passed:
                last_reason = FailureReason.REVIEW_FAILED
                feedback = "\n".join(review.findings) or review.summary
                if number < self.max_attempts:
                    record.transition_to(PlanStatus.FIXING)
                    self._event("repair_requested", record, {
                        "attempt": number, "reason": "review",
                    })
                    continue
                break

            record.transition_to(PlanStatus.PASSED)
            try:
                commit = session.commit(
                    f"optimize({candidate.id}): {candidate.title}"
                )
            except Exception as exc:
                record.fail(FailureReason.COMMIT_FAILED, str(exc))
                self._safe_rollback(record, plan_text, session)
                return record
            record.commit_sha = commit
            record.transition_to(PlanStatus.COMMITTED)
            self._event("plan_committed", record)
            self._save(record, plan_text, session)
            return record

        if record.status != PlanStatus.FAILED:
            record.fail(
                (
                    FailureReason.FIX_ATTEMPTS_EXHAUSTED
                    if last_reason in {
                        FailureReason.TEST_FAILED,
                        FailureReason.REVIEW_FAILED,
                    }
                    else last_reason
                ),
                feedback or "maximum repair attempts reached",
            )
        self._safe_rollback(record, plan_text, session)
        return record

    def integrate_plan(
        self, record: PlanRecord, session, integration_commands: list[str]
    ) -> PlanRecord:
        if record.status != PlanStatus.COMMITTED:
            return record
        record.transition_to(PlanStatus.INTEGRATING)
        self._event("integration_started", record)
        guard = getattr(self.git_session, "integration_guard", None)
        context = guard() if guard else _NullContext()
        with context:
            try:
                self.git_session.integrate(record.commit_sha)
            except git.GitCommandError as exc:
                self.git_session.abort_cherry_pick()
                record.fail(FailureReason.CHERRY_PICK_CONFLICT, str(exc))
                self._safe_rollback(record, "", session)
                return record
            tests = self.test_runner.run(
                self.git_session.integration_worktree,
                integration_commands,
            )
            if not tests.passed:
                self.git_session.abort_cherry_pick()
                record.fail(
                    FailureReason.INTEGRATION_TEST_FAILED,
                    self._test_summary(tests.commands),
                )
                self._safe_rollback(record, "", session)
                return record
        record.transition_to(PlanStatus.INTEGRATED)
        self._event("integration_completed", record)
        self._save(record, "", session)
        try:
            session.remove(delete_branch=False)
            self._event("worktree_cleaned", record)
        except Exception as exc:
            record.artifacts["cleanup_error"] = str(exc)
        return record

    def execute_plan(
        self, candidate: PlanCandidate, plan_text: str
    ) -> PlanRecord:
        try:
            session = self.git_session.create_plan_session(
                candidate.id, candidate.title
            )
        except Exception as exc:
            record = PlanRecord(candidate)
            record.fail(FailureReason.BRANCH_CREATE_FAILED, str(exc))
            return record
        record = self.develop_plan(candidate, plan_text, session)
        return self.integrate_plan(
            record, session, list(candidate.test_commands)
        )

    def _safe_rollback(self, record, plan_text, session) -> None:
        if session is None:
            return
        try:
            self._save(record, plan_text, session)
            session.rollback()
            if record.status == PlanStatus.FAILED:
                record.transition_to(PlanStatus.ROLLED_BACK)
            if self.recorder:
                self.recorder.save_plan(record, plan_text)
            self._event("plan_rolled_back", record)
            session.remove(delete_branch=True)
            self._event("worktree_cleaned", record)
        except Exception as exc:
            record.status = PlanStatus.FAILED
            record.failure_reason = FailureReason.ROLLBACK_FAILED
            record.failure_detail = str(exc)
            self._event("rollback_failed", record, {"error": str(exc)})

    def _save(self, record, plan_text, session) -> None:
        if not self.recorder:
            return
        self.recorder.save_plan(record, plan_text)
        self.recorder.save_diff(record.candidate.id, session.diff())

    def _persist_attempt(self, record, attempt, plan_text) -> None:
        if not self.recorder:
            return
        item_id = record.candidate.id
        self.recorder.save_plan(record, plan_text)
        self.recorder.save_attempt(item_id, attempt)
        if attempt.test_results:
            self.recorder.save_test_output(
                item_id,
                attempt.number,
                self._test_summary(attempt.test_results),
            )
        if attempt.review is not None:
            self.recorder.save_review(
                item_id, attempt.number, attempt.review
            )

    def _reserve_budget(self, stage: str) -> bool:
        if not self.cost_tracker:
            return True
        reserve = getattr(self.cost_tracker, "reserve", None)
        if reserve is None:
            return True
        amount = self.llm_reservation
        if amount is None:
            config = load_config()
            model = resolve_model(stage)[0]
            amount = estimate_call_cost(
                model,
                self._reservation_prompt,
                getattr(config.pipeline, "stage_output_tokens", {}).get(
                    stage, 4096
                ),
            )
            if amount is None:
                return self.cost_tracker.budget <= 0
        self._reserved_amount = amount
        return reserve(amount)

    def _release_budget(self) -> None:
        if not self.cost_tracker:
            return
        release = getattr(self.cost_tracker, "release", None)
        if release:
            release(self._reserved_amount)
        self._reserved_amount = 0.0

    def _record_cost(self, stage: str) -> dict | None:
        if not self.cost_tracker or not self.llm:
            return None
        usage = getattr(self.llm, "last_usage", None)
        if usage and not usage.is_empty:
            entry = self.cost_tracker.record_usage(
                stage, resolve_model(stage)[0], usage
            )
            if self.recorder:
                run = self.recorder.run
                run.spent = self.cost_tracker.spent
                run.total_cost = self.cost_tracker.spent
                run.remaining = (
                    self.cost_tracker.remaining
                    if self.cost_tracker.budget > 0 else None
                )
                run.cost_entries = [
                    cost_entry.to_dict()
                    for cost_entry in self.cost_tracker.entries
                ]
                self.recorder.save_state()
            return entry.to_dict()
        return None

    def _event(self, name: str, record: PlanRecord, payload=None) -> None:
        if not self.recorder:
            return
        data = {
            "item_id": record.candidate.id,
            "status": record.status.value,
        }
        data.update(payload or {})
        self.recorder.record_event(name, data)

    @staticmethod
    def _test_summary(commands) -> str:
        return "\n".join(
            f"{command.command}: exit {command.exit_code}\n"
            f"{command.stdout}\n{command.stderr}"
            for command in commands
        )


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False
