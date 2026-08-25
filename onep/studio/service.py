"""Application boundary for the OnePTeam Product Studio."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Any

from onep.config import load_config
from onep.domain import Problem
from onep.studio.articles import ArticleStudio
from onep.studio.discovery_service import ProductDiscoveryService
from onep.studio.discovery import raw_prd_structure_blockers
from onep.studio.knowledge import KnowledgeService
from onep.studio.models import ExecutionStrategy, FeatureSpec, StudioState
from onep.studio.product import (
    BaselineInspector,
    LiteLLMProductModel,
    ProductModel,
    compile_execution_units,
    normalize_prd,
    route_strategy,
)
from onep.studio.store import StudioStore


class StudioService:
    def __init__(
        self,
        store: StudioStore | None = None,
        *,
        product_model: ProductModel | None = None,
        baseline_inspector: BaselineInspector | None = None,
        articles: ArticleStudio | None = None,
    ) -> None:
        self.store = store or StudioStore()
        self.knowledge = KnowledgeService(self.store)
        self.product_model = product_model or LiteLLMProductModel()
        self.baseline_inspector = baseline_inspector or BaselineInspector()
        self.articles = articles or ArticleStudio(self.store, self.knowledge)
        self.discovery = ProductDiscoveryService(
            self.store, self.product_model, self.knowledge, self.baseline_inspector
        )

    def create_project(
        self, payload: dict[str, Any], *, action_id: str = ""
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        idea = str(payload.get("idea") or "").strip()
        if not idea:
            raise Problem(
                "idea_required",
                "Describe the product in one sentence",
                actionable=True,
            )
        name = str(payload.get("name") or "").strip() or self._project_name(idea)
        workspace = str(
            payload.get("repo") or payload.get("workspace_path") or ""
        ).strip()
        if not workspace:
            workspace = str(
                Path(load_config().project.root_dir).expanduser()
                / "workspaces"
                / self._slug(name)
            )
        baseline = self.baseline_inspector.inspect(workspace)
        project = self.store.create_project(name, idea, workspace)
        project = self.store.update_project(
            project["id"],
            baseline=baseline.to_dict(),
            state=StudioState.DISCOVERY.value,
        )
        result = self.discovery.start(project)
        self.store.remember_action(action_id, result)
        return result

    def answer_discovery(
        self, project_id: str, payload: dict[str, Any], *, action_id: str = ""
    ) -> dict[str, Any]:
        return self.discovery.answer(project_id, payload, action_id=action_id)

    def decide_discovery(
        self, project_id: str, payload: dict[str, Any], *, action_id: str = ""
    ) -> dict[str, Any]:
        return self.discovery.decide(project_id, payload, action_id=action_id)

    def reassess_discovery(
        self, project_id: str, *, action_id: str = ""
    ) -> dict[str, Any]:
        return self.discovery.reassess(project_id, action_id=action_id)

    def feedback_prd(
        self,
        project_id: str,
        version: int,
        payload: dict[str, Any],
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        return self.discovery.feedback_prd(
            project_id, version, payload, action_id=action_id
        )

    def revalidate_prd(self, project_id: str, version: int) -> dict[str, Any]:
        return self.discovery.revalidate_prd(project_id, version)

    def resolve_prd_assumption(
        self,
        project_id: str,
        version: int,
        assumption_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.discovery.resolve_assumption(
            project_id, version, assumption_id, payload
        )

    def approve_prd(
        self,
        project_id: str,
        version: int,
        payload: dict[str, Any],
        *,
        action_id: str = "",
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        prd = self.store.get_prd(project_id, version)
        requested = [str(v) for v in payload.get("feature_ids") or ()]
        if not requested:
            requested = [
                str(v) for v in prd["document"].get("release_feature_ids") or ()
            ]
        overrides = {
            str(feature_id): str(strategy)
            for feature_id, strategy in dict(
                payload.get("strategy_overrides") or {}
            ).items()
        }
        unknown_overrides = set(overrides) - set(requested)
        if unknown_overrides:
            raise Problem(
                "strategy_feature_not_in_release",
                "A strategy override targets a Feature outside this Release",
                ", ".join(sorted(unknown_overrides)),
            )
        invalid_strategies = {
            strategy
            for strategy in overrides.values()
            if strategy not in {value.value for value in ExecutionStrategy}
        }
        if invalid_strategies:
            raise Problem(
                "invalid_execution_strategy",
                "Invalid execution strategy",
                ", ".join(sorted(invalid_strategies)),
            )
        approved, release = self.store.approve_prd(project_id, version, requested)
        document = normalize_prd(
            approved["document"],
            self.baseline_inspector.inspect(
                self.store.get_project(project_id)["workspace_path"]
            ),
        )
        selected = set(release["feature_ids"])
        document = replace(
            document,
            release_feature_ids=(
                tuple(v for v in document.release_feature_ids if v in selected)
                or tuple(release["feature_ids"])
            ),
        )
        units = compile_execution_units(document, release["id"])
        units = self.store.replace_execution_units(project_id, release["id"], units)
        for feature_id, strategy in overrides.items():
            self.set_feature_strategy(
                project_id,
                feature_id,
                {
                    "strategy": strategy,
                    "reason": "用户在批准 Release 时覆盖自动策略",
                },
            )
        if overrides:
            units = self.store.execution_units(project_id, release["id"])
        self.knowledge.capture_decision(
            project_id=project_id,
            title=f"批准 PRD v{version} 与当前 Release",
            selected=", ".join(release["feature_ids"]),
            reason=str(payload.get("reason") or "用户确认产品定义与首发范围"),
            options=[
                feature["id"] for feature in prd["document"].get("features") or ()
            ],
            prd_version=version,
            release_id=release["id"],
        )
        result = {
            "project": self.store.get_project(project_id),
            "prd": approved,
            "release": release,
            "execution_units": units,
        }
        self.store.remember_action(action_id, result)
        return result

    def propose_change(
        self, project_id: str, payload: dict[str, Any], *, action_id: str = ""
    ) -> dict[str, Any]:
        replay = self.store.action_result(action_id)
        if replay is not None:
            return replay
        request = str(payload.get("request") or "").strip()
        if not request:
            raise Problem("change_request_required", "Describe the product change")
        project = self.store.get_project(project_id)
        previous = self.store.get_prd(project_id)
        context = self.knowledge.context(
            request,
            target_project_id=project_id,
            phase="product_change",
            technology_stack=project["baseline"].get("technology_stack") or (),
        )
        assessment = self.discovery._latest_assessment(project_id)
        raw = self.product_model.build_prd(
            project["idea"],
            project["baseline"],
            self.store.discovery_questions(project_id),
            context["rendered"],
            assessment.to_dict(),
            force_assumptions=True,
            change_request=request,
            previous_prd=previous["document"],
        )
        impact = dict(raw.pop("change_impact", {}) or {})
        structural_blockers = raw_prd_structure_blockers(raw)
        normalized = normalize_prd(
            raw, self.baseline_inspector.inspect(project["workspace_path"])
        )
        proposal = self.store.create_change_proposal(
            project_id, previous["version"], request, impact
        )
        validation = self.discovery._validate(
            project_id,
            normalized,
            assessment,
            structural_blockers=structural_blockers,
        )
        normalized = replace(
            normalized,
            validation_summary={
                **validation.to_dict(),
                "structural_blockers": list(structural_blockers),
            },
        )
        prd = self.store.create_prd(
            project_id,
            normalized.to_dict(),
            change_summary=request,
            status="review" if validation.passed else "draft",
        )
        self.store.save_prd_validation(project_id, prd["version"], validation.to_dict())
        self.store.create_product_assumptions(
            project_id, prd["version"], list(normalized.assumptions)
        )
        self.knowledge.capture_decision(
            project_id=project_id,
            title="提交产品变更并暂停受影响功能",
            selected=f"PRD v{prd['version']}",
            reason=request,
            options=(f"继续 v{previous['version']}", f"评审 v{prd['version']}"),
            prd_version=prd["version"],
        )
        result = {"proposal": proposal, "prd": prd, "impact": impact}
        self.store.remember_action(action_id, result)
        return result

    def set_feature_strategy(
        self, project_id: str, feature_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        strategy = str(payload.get("strategy") or "")
        if strategy not in {value.value for value in ExecutionStrategy}:
            raise Problem(
                "invalid_execution_strategy", "Invalid execution strategy", strategy
            )
        units = [
            unit
            for unit in self.store.execution_units(project_id)
            if unit["feature_id"] == feature_id
        ]
        if not units:
            raise Problem(
                "feature_not_in_release",
                "Feature has no current execution unit",
                feature_id,
            )
        if any(unit["status"] != "pending" for unit in units):
            raise Problem(
                "execution_strategy_locked",
                "Execution strategy cannot change after the Feature has started",
                feature_id,
            )
        reason = str(payload.get("reason") or "用户覆盖自动策略").strip()
        if strategy == ExecutionStrategy.AUTO.value:
            prd = self.store.get_prd(project_id)
            feature = next(
                (
                    value
                    for value in prd["document"].get("features") or ()
                    if str(value.get("id") or "") == feature_id
                ),
                None,
            )
            if feature is None:
                raise Problem("feature_not_found", "Feature not found", feature_id)
            strategy, automatic_reason = route_strategy(FeatureSpec.from_dict(feature))
            reason = f"重新自动选择：{automatic_reason}"
        updated = [
            self.store.update_execution_unit(
                unit["id"], strategy=strategy, strategy_reason=reason
            )
            for unit in units
        ]
        self.knowledge.capture_decision(
            project_id=project_id,
            title=f"覆盖功能 {feature_id} 的 Codex 模式",
            selected=strategy,
            reason=reason,
            options=[value.value for value in ExecutionStrategy],
            feature_id=feature_id,
        )
        return {"execution_units": updated}

    def resolve_interaction(
        self, interaction_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        pending = self.store.get_interaction(interaction_id)
        resolved = self.store.resolve_interaction(
            interaction_id,
            str(payload.get("response") or ""),
            int(payload.get("revision") or 0),
        )
        self.knowledge.capture_decision(
            project_id=resolved["project_id"],
            title=f"处理 {resolved['kind']} 交互请求",
            selected=resolved["response"][:2000],
            reason=pending["prompt"][:2000],
            options=tuple(pending.get("options") or ()),
            thread_id=resolved.get("thread_id") or "",
            turn_id=resolved.get("turn_id") or "",
        )
        return resolved

    def set_project_state(self, project_id: str, action: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if action == "pause":
            if project["state"] not in {
                StudioState.READY.value,
                StudioState.EXECUTING.value,
                StudioState.VERIFYING.value,
                StudioState.KNOWLEDGE_DISTILLING.value,
                StudioState.BLOCKED.value,
            }:
                raise Problem(
                    "project_not_pausable", "Project is not executing", project["state"]
                )
            state = StudioState.PAUSED.value
        elif action == "stop":
            state = StudioState.STOPPED.value
        elif action == "resume":
            if project["state"] not in {
                StudioState.PAUSED.value,
                StudioState.BLOCKED.value,
            }:
                raise Problem(
                    "project_not_resumable", "Project is not paused", project["state"]
                )
            if self.store.interactions(project_id, "pending"):
                raise Problem(
                    "interaction_resolution_required",
                    "Resolve the pending interaction before resuming",
                    actionable=True,
                    suggested_actions=("resolve_interaction",),
                )
            state = (
                StudioState.READY.value
                if self.store.current_release(project_id)
                else StudioState.DISCOVERY.value
            )
        else:
            raise Problem("invalid_project_action", "Invalid project action", action)
        return self.store.update_project(project_id, state=state)

    def studio(self, project_id: str) -> dict[str, Any]:
        snapshot = self.store.studio_snapshot(project_id)
        snapshot["change_proposals"] = self.store.change_proposals(project_id)
        return snapshot

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^\w一-鿿.-]+", "-", value.lower()).strip("-.")
        return slug[:60] or "onep-project"

    @classmethod
    def _project_name(cls, idea: str) -> str:
        value = re.sub(r"[。！？.!?].*$", "", idea).strip()
        return value[:30] or "新产品"
