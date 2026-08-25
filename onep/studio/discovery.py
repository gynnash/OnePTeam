"""Deterministic policy for adaptive, bounded product discovery."""

from __future__ import annotations

import re
from typing import Any

from onep.studio.models import (
    DiscoveryAssessment,
    DiscoveryCoverage,
    DiscoveryQuestionSpec,
    PRDValidation,
    PrdDocument,
)


BASE_DIMENSIONS = (
    "target_user",
    "core_problem",
    "primary_scenario",
    "value_proposition",
    "product_scope",
    "release_boundary",
    "success_metrics",
    "constraints",
)

RISK_DIMENSIONS = {
    "roles_permissions": ("登录", "注册", "权限", "角色", "auth", "login", "rbac"),
    "data_privacy": ("隐私", "个人信息", "用户数据", "敏感数据", "privacy", "pii"),
    "payments": ("支付", "付费", "订阅", "计费", "退款", "payment", "billing"),
    "migration": ("迁移", "导入", "兼容旧", "历史数据", "migration", "import"),
    "integrations": ("第三方", "集成", "webhook", "oauth", "integration"),
    "multi_tenant": ("多租户", "团队空间", "组织隔离", "tenant", "workspace"),
}

DIMENSION_LABELS = {
    "target_user": "目标用户",
    "core_problem": "核心问题",
    "primary_scenario": "主场景",
    "value_proposition": "价值主张",
    "product_scope": "产品范围",
    "release_boundary": "首发边界",
    "success_metrics": "成功指标",
    "constraints": "约束条件",
    "roles_permissions": "角色与权限",
    "data_privacy": "数据与隐私",
    "payments": "支付与计费",
    "migration": "数据迁移",
    "integrations": "外部集成",
    "multi_tenant": "多租户边界",
}

COVERAGE_LABELS = {
    DiscoveryCoverage.MISSING.value: "未确认",
    DiscoveryCoverage.CONFLICTED.value: "存在冲突",
    DiscoveryCoverage.ASSUMED.value: "仅为假设",
    DiscoveryCoverage.NOT_APPLICABLE.value: "不适用",
}


QUESTION_LIBRARY = {
    "target_user": (
        "谁是第一版必须优先服务的首要用户？",
        "决定产品定位、功能优先级和交互复杂度。",
    ),
    "core_problem": (
        "首要用户现在最痛、最需要被解决的具体问题是什么？",
        "决定产品是否解决了值得交付的问题。",
    ),
    "primary_scenario": (
        "用户会在什么具体场景中开始并完成一次核心任务？",
        "决定核心流程和功能边界。",
    ),
    "value_proposition": (
        "用户为什么会选择这个产品，而不是现有做法或替代方案？",
        "决定价值主张和差异化。",
    ),
    "product_scope": (
        "完整产品必须覆盖哪些能力，同时明确不做什么？",
        "防止范围缺口和隐性膨胀。",
    ),
    "release_boundary": (
        "第一版必须让用户完成的最小闭环是什么？",
        "决定当前 Release、依赖和交付成本。",
    ),
    "success_metrics": (
        "哪些可观察、可测量的结果代表第一版成功？",
        "决定验收标准和后续取舍。",
    ),
    "constraints": (
        "当前必须遵守哪些业务、技术、时间或资源约束？",
        "避免生成无法落地的产品方案。",
    ),
    "roles_permissions": (
        "不同用户角色分别能看到和操作什么？",
        "权限边界会影响产品流程、安全和数据模型。",
    ),
    "data_privacy": (
        "产品会处理哪些敏感数据，用户期望怎样授权、保留和删除？",
        "隐私决定数据边界与不可逆风险。",
    ),
    "payments": (
        "付费对象、计费单位、退款和失败处理规则分别是什么？",
        "支付规则会改变核心流程和验收范围。",
    ),
    "migration": (
        "哪些历史数据必须迁移，允许怎样的兼容和失败回退？",
        "迁移是高风险且通常不可逆的产品决定。",
    ),
    "integrations": (
        "哪些外部系统是首版必须依赖的，失败时用户应看到什么？",
        "外部依赖决定产品可用性和降级行为。",
    ),
    "multi_tenant": (
        "团队、组织和个人数据如何隔离、共享与转移？",
        "租户边界会影响权限、数据和协作模型。",
    ),
}


def required_dimensions(idea: str, baseline: dict[str, Any]) -> tuple[str, ...]:
    text = " ".join(
        (
            idea,
            *(str(item) for item in baseline.get("capabilities") or ()),
            *(str(item) for item in baseline.get("known_problems") or ()),
        )
    ).lower()
    dimensions = list(BASE_DIMENSIONS)
    for dimension, terms in RISK_DIMENSIONS.items():
        if any(term in text for term in terms):
            dimensions.append(dimension)
    return tuple(dimensions)


def fallback_questions(
    dimensions: list[str] | tuple[str, ...],
) -> list[DiscoveryQuestionSpec]:
    questions = []
    for dimension in dimensions:
        question, impact = QUESTION_LIBRARY.get(
            dimension,
            ("还需要确认哪个产品决定？", "这个决定会实质影响产品方向。"),
        )
        questions.append(
            DiscoveryQuestionSpec(
                question=question,
                impact=impact,
                dimension=dimension,
                required=True,
            )
        )
    return questions[:3]


class DiscoveryReadinessPolicy:
    """Combines model judgment with deterministic product-completeness gates."""

    minimum_score = 0.8

    def normalize(
        self,
        assessment: DiscoveryAssessment,
        *,
        idea: str,
        baseline: dict[str, Any],
        previous_questions: list[dict[str, Any]],
    ) -> DiscoveryAssessment:
        required = required_dimensions(idea, baseline)
        coverage = dict(assessment.coverage)
        for dimension in required:
            coverage.setdefault(dimension, DiscoveryCoverage.MISSING.value)

        blockers = []
        for dimension in required:
            status = coverage[dimension]
            if status in {
                DiscoveryCoverage.MISSING.value,
                DiscoveryCoverage.CONFLICTED.value,
                DiscoveryCoverage.ASSUMED.value,
            } or (
                dimension in BASE_DIMENSIONS
                and status == DiscoveryCoverage.NOT_APPLICABLE.value
            ):
                blockers.append(
                    f"{DIMENSION_LABELS.get(dimension, dimension)}："
                    f"{COVERAGE_LABELS.get(status, status)}"
                )
        blockers.extend(f"信息冲突：{item}" for item in assessment.conflicts)
        if assessment.open_decisions:
            blockers.extend(
                "高影响未决决定："
                f"{str(item.get('decision') or item.get('question') or item)[:500]}"
                for item in assessment.open_decisions
                if str(item.get("impact") or "high").lower()
                in {"high", "critical", "高", "严重", ""}
            )
        if assessment.readiness_score < self.minimum_score:
            blockers.append(
                f"产品定义完整度 {assessment.readiness_score:.0%} 低于"
                f" {self.minimum_score:.0%}"
            )
        if not assessment.ready_to_draft:
            blockers.append("产品模型仍判断信息不足，尚不能生成可审批 PRD")

        previous = {
            _question_key(str(item.get("question") or ""))
            for item in previous_questions
        }
        questions = []
        seen = set(previous)
        covered_dimensions = set()
        for question in assessment.next_questions:
            key = _question_key(question.question)
            if not key or key in seen:
                continue
            seen.add(key)
            questions.append(question)
            covered_dimensions.add(question.dimension)
        missing_dimensions = [
            dimension
            for dimension in required
            if coverage[dimension]
            in {
                DiscoveryCoverage.MISSING.value,
                DiscoveryCoverage.CONFLICTED.value,
                DiscoveryCoverage.ASSUMED.value,
            }
            or (
                dimension in BASE_DIMENSIONS
                and coverage[dimension] == DiscoveryCoverage.NOT_APPLICABLE.value
            )
        ]
        for question in fallback_questions(missing_dimensions):
            key = _question_key(question.question)
            if key not in seen and question.dimension not in covered_dimensions:
                seen.add(key)
                questions.append(question)
                covered_dimensions.add(question.dimension)

        return DiscoveryAssessment(
            ready_to_draft=assessment.ready_to_draft and not blockers,
            readiness_score=assessment.readiness_score,
            coverage=coverage,
            confirmed_facts=assessment.confirmed_facts,
            assumptions=assessment.assumptions,
            open_decisions=assessment.open_decisions,
            conflicts=assessment.conflicts,
            risk_flags=tuple(
                dict.fromkeys(
                    (*assessment.risk_flags, *required[len(BASE_DIMENSIONS) :])
                )
            ),
            next_questions=tuple(questions[:3]),
            policy_blockers=tuple(blockers),
        )

    @staticmethod
    def can_generate_prd(assessment: DiscoveryAssessment) -> bool:
        return assessment.ready_to_draft and not assessment.policy_blockers


def validate_prd(
    document: PrdDocument,
    model_validation: PRDValidation,
) -> PRDValidation:
    """Add deterministic blockers that the product model cannot waive."""
    blockers = list(model_validation.blockers)
    warnings = list(model_validation.warnings)
    definition = document.project_definition
    if not definition.target_users:
        blockers.append("PRD 缺少首要目标用户")
    if not definition.core_problem:
        blockers.append("PRD 缺少核心问题")
    if not definition.scenarios:
        blockers.append("PRD 缺少核心使用场景")
    if not definition.value_proposition:
        blockers.append("PRD 缺少价值主张")
    if not definition.success_metrics:
        blockers.append("PRD 缺少可观察的成功指标")
    if not definition.non_goals:
        blockers.append("PRD 缺少明确非目标")
    if not document.features:
        blockers.append("PRD 没有 Feature")
    if not document.requirements:
        blockers.append("PRD 没有 Requirement")
    if not document.release_feature_ids:
        blockers.append("PRD 没有当前 Release")
    feature_ids = [feature.id for feature in document.features]
    if len(feature_ids) != len(set(feature_ids)):
        blockers.append("PRD 存在重复的 Feature ID")
    unknown_release_features = set(document.release_feature_ids) - set(feature_ids)
    if unknown_release_features:
        blockers.append(
            "当前 Release 引用了不存在的 Feature："
            + ", ".join(sorted(unknown_release_features))
        )
    for feature in document.features:
        if not feature.product_role:
            blockers.append(f"Feature {feature.id} 缺少产品定位")
        if not feature.target_users:
            blockers.append(f"Feature {feature.id} 缺少目标用户")
        if not feature.user_outcome:
            blockers.append(f"Feature {feature.id} 缺少用户结果")
        if not feature.scope:
            blockers.append(f"Feature {feature.id} 缺少范围")
        if not feature.non_scope:
            warnings.append(f"Feature {feature.id} 未列出非范围")
        if not feature.flows:
            blockers.append(f"Feature {feature.id} 缺少用户流程")
        if not feature.rules:
            warnings.append(f"Feature {feature.id} 未列出独立产品规则")
        if not feature.acceptance:
            blockers.append(f"Feature {feature.id} 缺少验收标准")
        if not feature.metrics:
            warnings.append(f"Feature {feature.id} 缺少独立指标")
    blockers.extend(f"仍有未决问题：{item}" for item in document.open_questions)
    unique_blockers = tuple(dict.fromkeys(item for item in blockers if item))
    unique_warnings = tuple(dict.fromkeys(item for item in warnings if item))
    return PRDValidation(
        passed=model_validation.passed and not unique_blockers,
        blockers=unique_blockers,
        warnings=unique_warnings,
        issues=model_validation.issues,
        follow_up_questions=model_validation.follow_up_questions,
    )


def raw_prd_structure_blockers(value: dict[str, Any]) -> tuple[str, ...]:
    """Detect model-output defects before normalization can make them invisible."""
    features = [item for item in value.get("features") or () if isinstance(item, dict)]
    feature_ids = [str(item.get("id") or "").strip() for item in features]
    explicit_ids = [feature_id for feature_id in feature_ids if feature_id]
    blockers = []
    if len(explicit_ids) != len(set(explicit_ids)):
        blockers.append("原始 PRD 存在重复的 Feature ID")
    release_ids = {
        str(item).strip()
        for item in value.get("release_feature_ids") or ()
        if str(item).strip()
    }
    unknown = release_ids - set(explicit_ids)
    if unknown:
        blockers.append(
            "原始 PRD 的当前 Release 引用了不存在的 Feature："
            + ", ".join(sorted(unknown))
        )
    return tuple(blockers)


def _question_key(value: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", value.lower())[:500]
