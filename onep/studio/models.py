"""Domain types for the product, delivery, knowledge, and publishing studio."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StudioState(str, Enum):
    IDEA = "idea"
    DISCOVERY = "discovery"
    PRD_REVIEW = "prd_review"
    READY = "ready"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    KNOWLEDGE_DISTILLING = "knowledge_distilling"
    DELIVERED = "delivered"
    PAUSED = "paused"
    BLOCKED = "blocked"
    STOPPED = "stopped"


class PrdStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class DiscoverySessionStatus(str, Enum):
    ACTIVE = "active"
    CHECKPOINT = "checkpoint"
    READY = "ready"
    COMPLETED = "completed"


class DiscoveryCoverage(str, Enum):
    CONFIRMED = "confirmed"
    ASSUMED = "assumed"
    MISSING = "missing"
    CONFLICTED = "conflicted"
    NOT_APPLICABLE = "not_applicable"


class ExecutionStrategy(str, Enum):
    AUTO = "auto"
    DIRECT = "direct"
    PLAN = "plan_then_execute"
    GOAL = "goal"
    PLAN_GOAL = "plan_then_goal"


class KnowledgeValidity(str, Enum):
    OBSERVED = "observed"
    VALIDATED = "validated"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"


class KnowledgeApplicationResult(str, Enum):
    PENDING = "pending"
    HELPED = "helped"
    IRRELEVANT = "irrelevant"
    CONTRADICTED = "contradicted"


KNOWLEDGE_TYPES = {
    "problem",
    "hypothesis",
    "decision",
    "experiment",
    "failure",
    "discovery",
    "resolution",
    "pattern",
    "principle",
}


DISCOVERY_COVERAGE_VALUES = {value.value for value in DiscoveryCoverage}


@dataclass(frozen=True)
class DiscoveryQuestionSpec:
    question: str
    impact: str
    dimension: str
    question_type: str = "free_text"
    options: tuple[str, ...] = ()
    recommended_answer: str = ""
    recommendation_reason: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoveryQuestionSpec":
        question_type = str(
            value.get("type") or value.get("question_type") or "free_text"
        )
        if question_type not in {
            "free_text",
            "single_choice",
            "multi_choice",
            "confirm",
        }:
            question_type = "free_text"
        return cls(
            question=str(value.get("question") or "").strip()[:1000],
            impact=str(value.get("impact") or "").strip()[:1000],
            dimension=str(value.get("dimension") or "product_scope").strip()[:100],
            question_type=question_type,
            options=tuple(
                str(item).strip()[:500]
                for item in value.get("options") or ()
                if str(item).strip()
            )[:8],
            recommended_answer=str(value.get("recommended_answer") or "").strip()[
                :2000
            ],
            recommendation_reason=str(value.get("recommendation_reason") or "").strip()[
                :1000
            ],
            required=bool(value.get("required", True)),
        )


@dataclass(frozen=True)
class DiscoveryAssessment:
    ready_to_draft: bool
    readiness_score: float
    coverage: dict[str, str]
    confirmed_facts: tuple[str, ...] = ()
    assumptions: tuple[dict[str, Any], ...] = ()
    open_decisions: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    next_questions: tuple[DiscoveryQuestionSpec, ...] = ()
    policy_blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_to_draft": self.ready_to_draft,
            "readiness_score": self.readiness_score,
            "coverage": dict(self.coverage),
            "confirmed_facts": list(self.confirmed_facts),
            "assumptions": [dict(item) for item in self.assumptions],
            "open_decisions": [dict(item) for item in self.open_decisions],
            "conflicts": list(self.conflicts),
            "risk_flags": list(self.risk_flags),
            "next_questions": [question.to_dict() for question in self.next_questions],
            "policy_blockers": list(self.policy_blockers),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoveryAssessment":
        coverage = {
            str(key): str(item)
            if str(item) in DISCOVERY_COVERAGE_VALUES
            else DiscoveryCoverage.MISSING.value
            for key, item in dict(value.get("coverage") or {}).items()
        }
        try:
            score = float(value.get("readiness_score") or 0)
        except (TypeError, ValueError):
            score = 0
        return cls(
            ready_to_draft=bool(value.get("ready_to_draft")),
            readiness_score=min(1.0, max(0.0, score)),
            coverage=coverage,
            confirmed_facts=tuple(
                str(item)[:2000] for item in value.get("confirmed_facts") or ()
            ),
            assumptions=tuple(
                dict(item)
                for item in value.get("assumptions") or ()
                if isinstance(item, dict)
            ),
            open_decisions=tuple(
                dict(item)
                for item in value.get("open_decisions") or ()
                if isinstance(item, dict)
            ),
            conflicts=tuple(str(item)[:2000] for item in value.get("conflicts") or ()),
            risk_flags=tuple(str(item)[:200] for item in value.get("risk_flags") or ()),
            next_questions=tuple(
                DiscoveryQuestionSpec.from_dict(item)
                for item in value.get("next_questions") or ()
                if isinstance(item, dict) and str(item.get("question") or "").strip()
            )[:3],
            policy_blockers=tuple(
                str(item)[:1000] for item in value.get("policy_blockers") or ()
            ),
        )


@dataclass(frozen=True)
class PRDValidation:
    passed: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    issues: tuple[dict[str, Any], ...] = ()
    follow_up_questions: tuple[DiscoveryQuestionSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "issues": [dict(item) for item in self.issues],
            "follow_up_questions": [
                item.to_dict() for item in self.follow_up_questions
            ],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PRDValidation":
        blockers = tuple(str(item)[:2000] for item in value.get("blockers") or ())
        return cls(
            passed=bool(value.get("passed")) and not blockers,
            blockers=blockers,
            warnings=tuple(str(item)[:2000] for item in value.get("warnings") or ()),
            issues=tuple(
                dict(item)
                for item in value.get("issues") or ()
                if isinstance(item, dict)
            ),
            follow_up_questions=tuple(
                DiscoveryQuestionSpec.from_dict(item)
                for item in value.get("follow_up_questions") or ()
                if isinstance(item, dict) and str(item.get("question") or "").strip()
            )[:3],
        )


@dataclass(frozen=True)
class ProjectDefinition:
    target_users: tuple[str, ...] = ()
    core_problem: str = ""
    scenarios: tuple[str, ...] = ()
    value_proposition: str = ""
    differentiation: tuple[str, ...] = ()
    principles: tuple[str, ...] = ()
    success_metrics: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ProjectDefinition":
        data = value or {}
        return cls(
            target_users=tuple(str(v) for v in data.get("target_users") or ()),
            core_problem=str(data.get("core_problem") or ""),
            scenarios=tuple(str(v) for v in data.get("scenarios") or ()),
            value_proposition=str(data.get("value_proposition") or ""),
            differentiation=tuple(str(v) for v in data.get("differentiation") or ()),
            principles=tuple(str(v) for v in data.get("principles") or ()),
            success_metrics=tuple(str(v) for v in data.get("success_metrics") or ()),
            non_goals=tuple(str(v) for v in data.get("non_goals") or ()),
        )


@dataclass(frozen=True)
class CurrentProductBaseline:
    capabilities: tuple[str, ...] = ()
    current_users: tuple[str, ...] = ()
    architecture: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    known_problems: tuple[str, ...] = ()
    technical_debt: tuple[str, ...] = ()
    technology_stack: tuple[str, ...] = ()
    repository_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CurrentProductBaseline":
        data = value or {}
        return cls(
            capabilities=tuple(str(v) for v in data.get("capabilities") or ()),
            current_users=tuple(str(v) for v in data.get("current_users") or ()),
            architecture=tuple(str(v) for v in data.get("architecture") or ()),
            constraints=tuple(str(v) for v in data.get("constraints") or ()),
            known_problems=tuple(str(v) for v in data.get("known_problems") or ()),
            technical_debt=tuple(str(v) for v in data.get("technical_debt") or ()),
            technology_stack=tuple(str(v) for v in data.get("technology_stack") or ()),
            repository_fingerprint=str(data.get("repository_fingerprint") or ""),
        )


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    title: str
    product_role: str
    target_users: tuple[str, ...]
    user_outcome: str
    scope: tuple[str, ...]
    non_scope: tuple[str, ...]
    flows: tuple[str, ...]
    rules: tuple[str, ...]
    dependencies: tuple[str, ...]
    acceptance: tuple[str, ...]
    metrics: tuple[str, ...]
    verification_commands: tuple[str, ...] = ()
    parent_id: str = ""
    execution_strategy: str = ExecutionStrategy.AUTO.value
    strategy_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FeatureSpec":
        return cls(
            id=str(value.get("id") or new_id("feature")),
            title=str(value.get("title") or "Untitled feature"),
            product_role=str(value.get("product_role") or ""),
            target_users=tuple(str(v) for v in value.get("target_users") or ()),
            user_outcome=str(value.get("user_outcome") or ""),
            scope=tuple(str(v) for v in value.get("scope") or ()),
            non_scope=tuple(str(v) for v in value.get("non_scope") or ()),
            flows=tuple(str(v) for v in value.get("flows") or ()),
            rules=tuple(str(v) for v in value.get("rules") or ()),
            dependencies=tuple(str(v) for v in value.get("dependencies") or ()),
            acceptance=tuple(str(v) for v in value.get("acceptance") or ()),
            metrics=tuple(str(v) for v in value.get("metrics") or ()),
            verification_commands=tuple(
                str(v) for v in value.get("verification_commands") or ()
            ),
            parent_id=str(value.get("parent_id") or ""),
            execution_strategy=str(
                value.get("execution_strategy") or ExecutionStrategy.AUTO.value
            ),
            strategy_reason=str(value.get("strategy_reason") or ""),
        )


@dataclass(frozen=True)
class PrdDocument:
    project_definition: ProjectDefinition
    baseline: CurrentProductBaseline
    summary: str
    positioning: str
    requirements: tuple[dict[str, Any], ...]
    features: tuple[FeatureSpec, ...]
    release_feature_ids: tuple[str, ...]
    risks: tuple[str, ...] = ()
    assumptions: tuple[dict[str, Any], ...] = ()
    open_questions: tuple[str, ...] = ()
    decision_log: tuple[dict[str, Any], ...] = ()
    discovery_assessment_id: str = ""
    readiness_snapshot: dict[str, Any] = field(default_factory=dict)
    validation_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_definition": self.project_definition.to_dict(),
            "baseline": self.baseline.to_dict(),
            "summary": self.summary,
            "positioning": self.positioning,
            "requirements": list(self.requirements),
            "features": [feature.to_dict() for feature in self.features],
            "release_feature_ids": list(self.release_feature_ids),
            "risks": list(self.risks),
            "assumptions": [dict(item) for item in self.assumptions],
            "open_questions": list(self.open_questions),
            "decision_log": [dict(item) for item in self.decision_log],
            "discovery_assessment_id": self.discovery_assessment_id,
            "readiness_snapshot": dict(self.readiness_snapshot),
            "validation_summary": dict(self.validation_summary),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrdDocument":
        return cls(
            project_definition=ProjectDefinition.from_dict(
                value.get("project_definition")
            ),
            baseline=CurrentProductBaseline.from_dict(value.get("baseline")),
            summary=str(value.get("summary") or ""),
            positioning=str(value.get("positioning") or ""),
            requirements=tuple(
                dict(item)
                for item in value.get("requirements") or ()
                if isinstance(item, dict)
            ),
            features=tuple(
                FeatureSpec.from_dict(item)
                for item in value.get("features") or ()
                if isinstance(item, dict)
            ),
            release_feature_ids=tuple(
                str(v) for v in value.get("release_feature_ids") or ()
            ),
            risks=tuple(str(v) for v in value.get("risks") or ()),
            assumptions=tuple(
                dict(item)
                for item in value.get("assumptions") or ()
                if isinstance(item, dict)
            ),
            open_questions=tuple(str(v) for v in value.get("open_questions") or ()),
            decision_log=tuple(
                dict(item)
                for item in value.get("decision_log") or ()
                if isinstance(item, dict)
            ),
            discovery_assessment_id=str(value.get("discovery_assessment_id") or ""),
            readiness_snapshot=dict(value.get("readiness_snapshot") or {}),
            validation_summary=dict(value.get("validation_summary") or {}),
        )


@dataclass(frozen=True)
class KnowledgeRecord:
    id: str
    type: str
    title: str
    project_id: str
    summary: str = ""
    problem_context: str = ""
    options: tuple[str, ...] = ()
    selected: str = ""
    reason: str = ""
    impact: str = ""
    failure_symptom: str = ""
    error_signature: str = ""
    failed_hypotheses: tuple[str, ...] = ()
    attempted_fixes: tuple[str, ...] = ()
    root_cause: str = ""
    final_fix: str = ""
    prevention: str = ""
    observations: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    human_decisions: tuple[str, ...] = ()
    confidence: float = 0.5
    generalizable: bool = False
    validity: str = KnowledgeValidity.OBSERVED.value
    technology_stack: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    problem_category: str = ""
    tags: tuple[str, ...] = ()
    prd_version: int = 0
    feature_id: str = ""
    release_id: str = ""
    execution_unit_id: str = ""
    thread_id: str = ""
    turn_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    code_fingerprint: str = ""
    artifact_refs: tuple[str, ...] = ()
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    revision: int = 1

    def __post_init__(self) -> None:
        if self.type not in KNOWLEDGE_TYPES:
            raise ValueError(f"invalid knowledge type: {self.type}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("knowledge confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InteractionRequest:
    id: str
    project_id: str
    kind: str
    prompt: str
    status: str = "pending"
    options: tuple[str, ...] = ()
    response: str = ""
    thread_id: str = ""
    turn_id: str = ""
    created_at: str = field(default_factory=now)
    resolved_at: str = ""
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
