"""Product discovery, repository baseline, PRD generation, and strategy routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Protocol

from onep.config import load_config
from onep.delivery.fingerprint import fingerprint_tree
from onep.domain import Problem
from onep.studio.models import (
    CurrentProductBaseline,
    ExecutionStrategy,
    FeatureSpec,
    PrdDocument,
    ProjectDefinition,
    new_id,
)
from onep.studio.privacy import sanitize_for_model


class ProductModel(Protocol):
    def assess_discovery(
        self,
        idea: str,
        baseline: dict[str, Any],
        transcript: list[dict[str, Any]],
        knowledge_context: str,
        previous_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def build_prd(
        self,
        idea: str,
        baseline: dict[str, Any],
        transcript: list[dict[str, Any]],
        knowledge_context: str,
        assessment: dict[str, Any],
        force_assumptions: bool = False,
        change_request: str = "",
        previous_prd: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def validate_prd(
        self,
        prd: dict[str, Any],
        transcript: list[dict[str, Any]],
        assessment: dict[str, Any],
    ) -> dict[str, Any]: ...


def _json_object(value: str) -> dict[str, Any]:
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise Problem(
                "product_model_invalid_output",
                "Product model returned invalid JSON",
                str(exc),
                actionable=True,
                suggested_actions=("retry", "test_model"),
            ) from exc
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as nested:
            raise Problem(
                "product_model_invalid_output",
                "Product model returned invalid JSON",
                str(nested),
                actionable=True,
                suggested_actions=("retry", "test_model"),
            ) from nested
    if not isinstance(parsed, dict):
        raise Problem(
            "product_model_invalid_output", "Product model returned non-object JSON"
        )
    return parsed


class LiteLLMProductModel:
    """Provider-independent product reasoning through the configured LiteLLM model."""

    def __init__(self, llm=None) -> None:
        self.llm = llm or LiteLLMProductClient()

    def assess_discovery(
        self,
        idea: str,
        baseline: dict[str, Any],
        transcript: list[dict[str, Any]],
        knowledge_context: str,
        previous_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = {
            "ready_to_draft": False,
            "readiness_score": 0.0,
            "coverage": {
                "target_user": "missing",
                "core_problem": "missing",
                "primary_scenario": "missing",
                "value_proposition": "missing",
                "product_scope": "missing",
                "release_boundary": "missing",
                "success_metrics": "missing",
                "constraints": "missing",
            },
            "confirmed_facts": ["仅写有来源的已确认事实"],
            "assumptions": [
                {
                    "statement": "模型推断",
                    "source": "model",
                    "impact": "",
                    "risk": "low|medium|high|critical",
                }
            ],
            "open_decisions": [{"decision": "", "impact": "high|medium|low"}],
            "conflicts": [],
            "risk_flags": [],
            "next_questions": [
                {
                    "dimension": "target_user",
                    "question": "问题",
                    "impact": "影响",
                    "question_type": "free_text|single_choice|multi_choice|confirm",
                    "options": [],
                    "recommended_answer": "",
                    "recommendation_reason": "",
                    "required": True,
                }
            ],
        }
        prompt = f"""用户的一句话需求：{idea}
现有产品基线：{json.dumps(baseline, ensure_ascii=False)}
完整 Discovery 问答：{json.dumps(transcript, ensure_ascii=False)}
上一轮评估：{json.dumps(previous_assessment or {}, ensure_ascii=False)}
相关历史经验（仅是带来源的先验，不是当前事实）：
{knowledge_context or "无"}

评估当前信息是否足以形成决策完整的 PRD。coverage 只能使用
confirmed、assumed、missing、conflicted、not_applicable。
只返回符合这个形状的 JSON：
{json.dumps(schema, ensure_ascii=False)}

next_questions 每轮最多三个，按产品影响、不确定性、不可逆性和风险排序；
只问会改变定位、范围、规则、验收或高风险边界的问题，不要询问代码库可以发现的事实；
模型补全必须进入 assumptions，不能写成 confirmed；有高影响未决决定时 ready_to_draft 必须为 false。"""
        try:
            response = self.llm.invoke(
                system_prompt=(
                    "你是 OnePTeam 的产品发现评估模型。判断信息充分度并提出最少的高价值问题。"
                    "不编写代码，不调用工具，不把推断伪装成事实，只返回指定 JSON。"
                ),
                user_prompt=sanitize_for_model(prompt, max_chars=40_000),
                stage_name="product_discovery",
            )
        except Exception as exc:
            raise Problem(
                "product_model_unavailable",
                "Product model is unavailable",
                sanitize_for_model(str(exc), max_chars=2000),
                actionable=True,
                suggested_actions=("configure_model", "retry"),
            ) from exc
        return _json_object(response)

    def build_prd(
        self,
        idea: str,
        baseline: dict[str, Any],
        transcript: list[dict[str, Any]],
        knowledge_context: str,
        assessment: dict[str, Any],
        force_assumptions: bool = False,
        change_request: str = "",
        previous_prd: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = {
            "project_definition": {
                "target_users": [""],
                "core_problem": "",
                "scenarios": [""],
                "value_proposition": "",
                "differentiation": [""],
                "principles": [""],
                "success_metrics": [""],
                "non_goals": [""],
            },
            "summary": "",
            "positioning": "",
            "requirements": [{"id": "req_1", "title": "", "priority": "P1"}],
            "features": [
                {
                    "id": "feature_1",
                    "title": "",
                    "product_role": "",
                    "target_users": [""],
                    "user_outcome": "",
                    "scope": [""],
                    "non_scope": [""],
                    "flows": [""],
                    "rules": [""],
                    "dependencies": [],
                    "acceptance": [""],
                    "metrics": [""],
                    "verification_commands": [
                        "聚焦测试命令",
                        "作用域测试命令",
                        "完整质量门命令",
                    ],
                    "parent_id": "",
                }
            ],
            "release_feature_ids": ["feature_1"],
            "risks": [""],
            "assumptions": [
                {
                    "statement": "",
                    "source": "model|user|baseline|knowledge",
                    "impact": "",
                    "risk": "low|medium|high|critical",
                }
            ],
            "open_questions": [],
            "decision_log": [{"decision": "", "source": "", "reason": ""}],
            "change_impact": {
                "affected_feature_ids": [],
                "invalidated_evidence_ids": [],
                "summary": "",
            },
        }
        prompt = f"""创建一份完整、可交付的中文产品 PRD。
一句话需求：{idea}
代码库基线：{json.dumps(baseline, ensure_ascii=False)}
完整 Discovery 问答：{json.dumps(transcript, ensure_ascii=False)}
最终 Discovery Assessment：{json.dumps(assessment, ensure_ascii=False)}
相关历史经验（带来源的先验，必须明确验证后才能采用）：
{knowledge_context or "无"}
用户是否要求带假设生成草稿：{force_assumptions}
变更请求：{change_request or "无"}
上一版 PRD：{json.dumps(previous_prd or {}, ensure_ascii=False)}

只返回符合这个形状的 JSON：
{json.dumps(schema, ensure_ascii=False)}

要求：完整描述产品定位和全部重要功能，但 release_feature_ids 只选择最小可验证首发范围；
每个 Feature 必须说明其产品角色、用户结果、范围、非范围、流程、规则、依赖、验收和指标；
verification_commands 按聚焦、作用域、完整质量门的顺序给出 1 到 3 条可离线直接执行的命令；
任何未经用户或代码基线确认的补全都必须写入 assumptions；仍会改变产品方向的问题写入 open_questions；
所有 ID 在同一项目中稳定、简短，需求变化时保留未改变 Feature 的 ID。"""
        try:
            response = self.llm.invoke(
                system_prompt=(
                    "你是 OnePTeam 的首席产品负责人。输出可审核、可追溯、可执行的 PRD JSON。"
                    "不编写代码，不调用工具，不把历史经验误写成当前事实。"
                ),
                user_prompt=sanitize_for_model(prompt, max_chars=60_000),
                stage_name="product_prd",
            )
        except Exception as exc:
            raise Problem(
                "product_model_unavailable",
                "Product model is unavailable",
                sanitize_for_model(str(exc), max_chars=2000),
                actionable=True,
                suggested_actions=("configure_model", "retry"),
            ) from exc
        return _json_object(response)

    def validate_prd(
        self,
        prd: dict[str, Any],
        transcript: list[dict[str, Any]],
        assessment: dict[str, Any],
    ) -> dict[str, Any]:
        schema = {
            "passed": False,
            "blockers": [],
            "warnings": [],
            "issues": [
                {
                    "type": "gap|conflict|untestable|risk|assumption",
                    "severity": "blocker|warning",
                    "message": "",
                }
            ],
            "follow_up_questions": [
                {
                    "dimension": "product_scope",
                    "question": "",
                    "impact": "",
                    "question_type": "free_text",
                    "options": [],
                    "required": True,
                }
            ],
        }
        prompt = f"""验证这份 PRD 是否与 Discovery 决策一致且可以进入人工审批。
PRD：{json.dumps(prd, ensure_ascii=False)}
Discovery 问答：{json.dumps(transcript, ensure_ascii=False)}
Assessment：{json.dumps(assessment, ensure_ascii=False)}

检查产品定位、范围、非范围、Feature 覆盖、冲突、风险、假设、验收可测性和 Release 最小闭环。
不要增加新产品需求。存在会改变产品方向的缺口时给出 blocker 和最多三个 follow_up_questions。
只返回符合这个形状的 JSON：
{json.dumps(schema, ensure_ascii=False)}"""
        try:
            response = self.llm.invoke(
                system_prompt=(
                    "你是 OnePTeam 的独立 PRD 审核模型。只验证事实、决策一致性和可验收性，"
                    "不编写代码，不调用工具，只返回指定 JSON。"
                ),
                user_prompt=sanitize_for_model(prompt, max_chars=60_000),
                stage_name="product_prd_validation",
            )
        except Exception as exc:
            raise Problem(
                "product_model_unavailable",
                "Product model is unavailable",
                sanitize_for_model(str(exc), max_chars=2000),
                actionable=True,
                suggested_actions=("configure_model", "retry"),
            ) from exc
        return _json_object(response)


class LiteLLMProductClient:
    """Minimal product-only LiteLLM client."""

    def invoke(self, system_prompt: str, user_prompt: str, stage_name: str) -> str:
        del stage_name
        from litellm import completion

        config = load_config().llm
        provider = config.default_provider
        provider_config = config.models.get(provider, {})
        environment_prefix = re.sub(r"[^A-Z0-9]+", "_", provider.upper())
        api_key = os.environ.get(
            f"{environment_prefix}_API_KEY",
            str(provider_config.get("api_key") or ""),
        )
        api_base = os.environ.get(
            f"{environment_prefix}_API_BASE",
            str(provider_config.get("api_base") or ""),
        )
        parameters: dict[str, Any] = {
            "model": config.default_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if api_key:
            parameters["api_key"] = api_key
        if api_base:
            parameters["api_base"] = api_base
        response = completion(**parameters)
        return str(response.choices[0].message.content or "")


class BaselineInspector:
    """Bounded read-only repository inspection used before product discovery."""

    MAX_FILES = 3000
    MAX_READ_BYTES = 250_000

    STACK_FILES = {
        "pyproject.toml": "Python",
        "requirements.txt": "Python",
        "package.json": "JavaScript/TypeScript",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "pubspec.yaml": "Flutter/Dart",
        "pom.xml": "Java",
        "build.gradle": "Java/Kotlin",
    }

    def inspect(self, workspace_path: str) -> CurrentProductBaseline:
        if not workspace_path:
            return CurrentProductBaseline()
        root = Path(workspace_path).expanduser().resolve()
        if not root.exists():
            return CurrentProductBaseline()
        if not root.is_dir():
            raise Problem(
                "workspace_not_directory", "Workspace is not a directory", str(root)
            )
        paths = []
        for path in root.rglob("*"):
            if len(paths) >= self.MAX_FILES:
                break
            if any(
                part in {".git", ".onep", "node_modules", "target", ".venv"}
                for part in path.parts
            ):
                continue
            if path.is_file():
                paths.append(path)
        technology_stack = sorted(
            {
                stack
                for filename, stack in self.STACK_FILES.items()
                if (root / filename).exists()
            }
        )
        architecture = []
        for folder in (
            "src",
            "app",
            "onep",
            "web",
            "server",
            "client",
            "tests",
            "docs",
        ):
            if (root / folder).is_dir():
                architecture.append(f"{folder}/")
        read_budget = self.MAX_READ_BYTES
        texts: list[str] = []
        for filename in ("README.md", "README.rst", "pyproject.toml", "package.json"):
            path = root / filename
            if not path.is_file() or read_budget <= 0:
                continue
            data = path.read_bytes()[:read_budget]
            read_budget -= len(data)
            texts.append(data.decode("utf-8", "replace"))
        combined = "\n".join(texts)
        capabilities = [
            line.lstrip("#*- ").strip()[:240]
            for line in combined.splitlines()
            if line.strip().startswith(("## ", "### ", "- "))
        ][:24]
        constraints = []
        if (root / ".git").exists():
            constraints.append(
                "Existing Git repository; preserve current product behavior"
            )
        if len(paths) >= self.MAX_FILES:
            constraints.append(
                "Repository baseline was sampled at the file-count limit"
            )
        try:
            digest = fingerprint_tree(root).digest
        except (OSError, ValueError):
            digest = ""
        return CurrentProductBaseline(
            capabilities=tuple(capabilities),
            architecture=tuple(architecture),
            constraints=tuple(constraints),
            technology_stack=tuple(technology_stack),
            repository_fingerprint=digest,
        )


def normalize_prd(raw: dict[str, Any], baseline: CurrentProductBaseline) -> PrdDocument:
    definition = ProjectDefinition.from_dict(raw.get("project_definition"))
    raw_features = [
        dict(item) for item in raw.get("features") or () if isinstance(item, dict)
    ]
    seen: set[str] = set()
    features = []
    for index, item in enumerate(raw_features, start=1):
        feature_id = str(item.get("id") or f"feature_{index}")
        if feature_id in seen:
            feature_id = new_id("feature")
        seen.add(feature_id)
        item["id"] = feature_id
        feature = FeatureSpec.from_dict(item)
        strategy, reason = route_strategy(feature)
        features.append(
            FeatureSpec.from_dict(
                {
                    **feature.to_dict(),
                    "execution_strategy": strategy,
                    "strategy_reason": reason,
                }
            )
        )
    if not features:
        raise Problem("prd_has_no_features", "PRD must contain at least one feature")
    release_ids = [
        value
        for value in (str(v) for v in raw.get("release_feature_ids") or ())
        if value in seen
    ]
    if not release_ids:
        release_ids = [features[0].id]
    requirements = tuple(
        dict(item) for item in raw.get("requirements") or () if isinstance(item, dict)
    )
    return PrdDocument(
        project_definition=definition,
        baseline=baseline,
        summary=str(raw.get("summary") or ""),
        positioning=str(raw.get("positioning") or ""),
        requirements=requirements,
        features=tuple(features),
        release_feature_ids=tuple(dict.fromkeys(release_ids)),
        risks=tuple(str(v) for v in raw.get("risks") or ()),
        assumptions=tuple(
            dict(item)
            for item in raw.get("assumptions") or ()
            if isinstance(item, dict)
            and str(item.get("statement") or item.get("assumption") or "").strip()
        ),
        open_questions=tuple(str(v) for v in raw.get("open_questions") or ()),
        decision_log=tuple(
            dict(item)
            for item in raw.get("decision_log") or ()
            if isinstance(item, dict)
        ),
        discovery_assessment_id=str(raw.get("discovery_assessment_id") or ""),
        readiness_snapshot=dict(raw.get("readiness_snapshot") or {}),
        validation_summary=dict(raw.get("validation_summary") or {}),
    )


def route_strategy(feature: FeatureSpec) -> tuple[str, str]:
    text = " ".join(
        (
            feature.title,
            feature.product_role,
            feature.user_outcome,
            *feature.scope,
            *feature.flows,
            *feature.rules,
            *feature.acceptance,
        )
    ).lower()
    long_running = any(
        term in text
        for term in (
            "持续",
            "反复",
            "收敛",
            "优化",
            "监控",
            "定量",
            "长期",
            "迭代",
            "benchmark",
            "converge",
            "monitor",
        )
    )
    architectural = (
        bool(feature.dependencies)
        or len(feature.scope) > 3
        or any(
            term in text
            for term in (
                "架构",
                "数据库",
                "schema",
                "api",
                "迁移",
                "跨模块",
                "权限",
                "安全",
                "并发",
                "协议",
            )
        )
    )
    if long_running and architectural:
        return (
            ExecutionStrategy.PLAN_GOAL.value,
            "长期收敛目标且存在跨模块或架构不确定性",
        )
    if long_running:
        return ExecutionStrategy.GOAL.value, "需要反复测量或持续收敛"
    if architectural:
        return ExecutionStrategy.PLAN.value, "涉及依赖、跨模块、API、Schema 或架构变化"
    return ExecutionStrategy.DIRECT.value, "边界清晰、影响局部且验收可直接验证"


def compile_execution_units(prd: PrdDocument, release_id: str) -> list[dict[str, Any]]:
    selected = set(prd.release_feature_ids)
    requirements = {str(value.get("id") or ""): value for value in prd.requirements}
    units = []
    for feature in prd.features:
        if feature.id not in selected:
            continue
        linked_requirements = [
            requirement_id
            for requirement_id, value in requirements.items()
            if requirement_id
            and (
                feature.id in value.get("feature_ids", [])
                or not value.get("feature_ids")
            )
        ]
        units.append(
            {
                "id": new_id("unit"),
                "release_id": release_id,
                "feature_id": feature.id,
                "title": feature.title,
                "objective": feature.user_outcome,
                "requirement_ids": linked_requirements,
                "acceptance": list(feature.acceptance),
                "verification_commands": list(feature.verification_commands),
                "dependencies": [v for v in feature.dependencies if v in selected],
                "expected_paths": [],
                "strategy": feature.execution_strategy,
                "strategy_reason": feature.strategy_reason,
                "status": "pending",
            }
        )
    return units
