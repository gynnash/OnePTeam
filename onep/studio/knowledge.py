"""Structured engineering knowledge capture, retrieval, and reuse feedback."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from onep.domain import Problem
from onep.studio.models import (
    KNOWLEDGE_TYPES,
    KnowledgeApplicationResult,
    KnowledgeRecord,
    KnowledgeValidity,
    new_id,
)
from onep.studio.store import StudioStore
from onep.studio.privacy import sanitize_for_model


_TOKEN = re.compile(r"[\w.#+/-]+", re.UNICODE)


def _tokens(value: str) -> set[str]:
    return {
        token.lower() for token in _TOKEN.findall(value or "")
        if len(token) > 1
    }


class KnowledgeService:
    MAX_CONTEXT_RECORDS = 6
    MAX_CONTEXT_CHARS = 6000

    def __init__(self, store: StudioStore) -> None:
        self.store = store

    def capture(self, **values: Any) -> dict[str, Any]:
        record_type = str(values.get("type") or "").lower()
        if record_type not in KNOWLEDGE_TYPES:
            raise Problem(
                "invalid_knowledge_type", "Unsupported knowledge type", record_type
            )
        record = KnowledgeRecord(
            id=str(values.get("id") or new_id("knowledge")),
            type=record_type,
            title=str(values.get("title") or values.get("summary") or record_type)[:160],
            project_id=str(values.get("project_id") or ""),
            summary=str(values.get("summary") or "")[:4000],
            problem_context=str(values.get("problem_context") or "")[:4000],
            options=tuple(str(v)[:1000] for v in values.get("options") or ()),
            selected=str(values.get("selected") or "")[:2000],
            reason=str(values.get("reason") or "")[:4000],
            impact=str(values.get("impact") or "")[:2000],
            failure_symptom=str(values.get("failure_symptom") or "")[:4000],
            error_signature=str(values.get("error_signature") or "")[:1000],
            failed_hypotheses=tuple(
                str(v)[:1000] for v in values.get("failed_hypotheses") or ()
            ),
            attempted_fixes=tuple(
                str(v)[:1000] for v in values.get("attempted_fixes") or ()
            ),
            root_cause=str(values.get("root_cause") or "")[:4000],
            final_fix=str(values.get("final_fix") or "")[:4000],
            prevention=str(values.get("prevention") or "")[:4000],
            observations=tuple(
                str(v)[:1000] for v in values.get("observations") or ()
            ),
            inferences=tuple(str(v)[:1000] for v in values.get("inferences") or ()),
            human_decisions=tuple(
                str(v)[:1000] for v in values.get("human_decisions") or ()
            ),
            confidence=float(values.get("confidence", 0.5)),
            generalizable=bool(values.get("generalizable", False)),
            validity=str(values.get("validity") or KnowledgeValidity.OBSERVED.value),
            technology_stack=tuple(
                str(v)[:100] for v in values.get("technology_stack") or ()
            ),
            components=tuple(str(v)[:200] for v in values.get("components") or ()),
            problem_category=str(values.get("problem_category") or "")[:200],
            tags=tuple(str(v)[:100] for v in values.get("tags") or ()),
            prd_version=int(values.get("prd_version") or 0),
            feature_id=str(values.get("feature_id") or ""),
            release_id=str(values.get("release_id") or ""),
            execution_unit_id=str(values.get("execution_unit_id") or ""),
            thread_id=str(values.get("thread_id") or ""),
            turn_id=str(values.get("turn_id") or ""),
            evidence_ids=tuple(str(v) for v in values.get("evidence_ids") or ()),
            code_fingerprint=str(values.get("code_fingerprint") or ""),
            artifact_refs=tuple(str(v) for v in values.get("artifact_refs") or ()),
        )
        return self.store.put_knowledge(record)

    def capture_decision(
        self,
        *,
        project_id: str,
        title: str,
        selected: str,
        reason: str,
        options: list[str] | tuple[str, ...] = (),
        **links: Any,
    ) -> dict[str, Any]:
        return self.capture(
            type="decision", project_id=project_id, title=title,
            summary=f"选择 {selected}：{reason}", options=options,
            selected=selected, reason=reason, human_decisions=(selected,),
            confidence=1.0, validity="validated", **links,
        )

    def capture_failure(
        self,
        *,
        project_id: str,
        title: str,
        symptom: str,
        error_signature: str = "",
        attempted_fixes: list[str] | tuple[str, ...] = (),
        root_cause: str = "",
        final_fix: str = "",
        **links: Any,
    ) -> dict[str, Any]:
        validity = "validated" if root_cause and final_fix else "observed"
        return self.capture(
            type="failure", project_id=project_id, title=title,
            summary=root_cause or symptom, failure_symptom=symptom,
            error_signature=error_signature, attempted_fixes=attempted_fixes,
            root_cause=root_cause, final_fix=final_fix,
            confidence=0.9 if root_cause else 0.5, validity=validity,
            generalizable=bool(error_signature and root_cause), **links,
        )

    def search(
        self,
        query: str,
        *,
        project_ids: list[str] | tuple[str, ...] = (),
        technology_stack: list[str] | tuple[str, ...] = (),
        components: list[str] | tuple[str, ...] = (),
        error_signature: str = "",
        include_invalid: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_tokens = _tokens(
            " ".join((query, error_signature, *technology_stack, *components))
        )
        project_filter = set(project_ids)
        candidates = self.store.knowledge_rows()
        applications = self.store.knowledge_applications()
        outcomes: dict[str, list[str]] = {}
        for application in applications:
            outcomes.setdefault(application["knowledge_id"], []).append(
                application["result"]
            )
        ranked: list[tuple[float, dict[str, Any]]] = []
        for record in candidates:
            if project_filter and record["project_id"] not in project_filter:
                continue
            if not include_invalid and record["validity"] in {
                KnowledgeValidity.CONTRADICTED.value,
                KnowledgeValidity.SUPERSEDED.value,
            }:
                continue
            searchable = " ".join(
                str(value) for value in (
                    record.get("title"), record.get("summary"),
                    record.get("problem_context"), record.get("error_signature"),
                    record.get("root_cause"), record.get("final_fix"),
                    record.get("problem_category"),
                    *(record.get("technology_stack") or ()),
                    *(record.get("components") or ()), *(record.get("tags") or ()),
                ) if value
            )
            record_tokens = _tokens(searchable)
            overlap = len(query_tokens & record_tokens)
            if query_tokens and overlap == 0:
                continue
            score = overlap * 2.0
            if error_signature and error_signature.lower() in searchable.lower():
                score += 8
            score += float(record.get("confidence") or 0)
            if record.get("validity") == KnowledgeValidity.VALIDATED.value:
                score += 1.5
            if record.get("generalizable"):
                score += 0.5
            score += outcomes.get(record["id"], []).count("helped")
            score -= outcomes.get(record["id"], []).count("irrelevant") * 0.5
            score -= outcomes.get(record["id"], []).count("contradicted") * 2.0
            ranked.append((score, record))
        ranked.sort(key=lambda value: (-value[0], value[1]["updated_at"]))
        return [{**record, "relevance_score": round(score, 3)}
                for score, record in ranked[: min(max(1, limit), 50)]]

    def context(
        self,
        query: str,
        *,
        target_project_id: str,
        phase: str,
        feature_id: str = "",
        technology_stack: list[str] | tuple[str, ...] = (),
        components: list[str] | tuple[str, ...] = (),
        error_signature: str = "",
    ) -> dict[str, Any]:
        records = self.search(
            query, technology_stack=technology_stack, components=components,
            error_signature=error_signature, limit=self.MAX_CONTEXT_RECORDS * 3,
        )
        records = [
            r for r in records if r["project_id"] != target_project_id
        ][: self.MAX_CONTEXT_RECORDS]
        rendered = []
        used = 0
        for record in records:
            text = (
                f"[{record['id']}] 来源项目=[已泛化] "
                f"状态={record['validity']} 可信度={record['confidence']:.2f}\n"
                f"{record['title']}：{record.get('summary') or ''}\n"
                f"适用条件/证据：{record.get('problem_context') or record.get('root_cause') or '未记录'}"
            )
            text = sanitize_for_model(text, max_chars=self.MAX_CONTEXT_CHARS)
            if used + len(text) > self.MAX_CONTEXT_CHARS:
                break
            rendered.append(text)
            used += len(text)
            self.store.save_knowledge_application(
                {
                    "knowledge_id": record["id"],
                    "target_project_id": target_project_id,
                    "feature_id": feature_id,
                    "phase": phase,
                    "reason": f"与当前问题相关，检索分数 {record['relevance_score']}",
                    "result": KnowledgeApplicationResult.PENDING.value,
                }
            )
        return {
            "records": records[: len(rendered)],
            "rendered": "\n\n".join(rendered),
            "bounded": True,
            "sanitized": True,
            "max_records": self.MAX_CONTEXT_RECORDS,
            "max_chars": self.MAX_CONTEXT_CHARS,
        }

    def feedback(
        self, knowledge_id: str, target_project_id: str, feature_id: str,
        phase: str, result: str, feedback: str = "",
    ) -> dict[str, Any]:
        if result not in {value.value for value in KnowledgeApplicationResult}:
            raise Problem("invalid_knowledge_feedback", "Invalid knowledge result", result)
        record = self.store.get_knowledge(knowledge_id)
        application = self.store.save_knowledge_application(
            {
                "knowledge_id": knowledge_id, "target_project_id": target_project_id,
                "feature_id": feature_id, "phase": phase,
                "reason": "explicit reuse feedback", "result": result,
                "adopted_as": feedback, "feedback": feedback,
            }
        )
        delta = {
            "helped": 0.05, "irrelevant": -0.03, "contradicted": -0.15,
            "pending": 0,
        }[result]
        validity = record["validity"]
        next_confidence = min(1.0, max(0.0, float(record["confidence"]) + delta))
        current = KnowledgeRecord(**{
            key: record[key] for key in KnowledgeRecord.__dataclass_fields__
        })
        self.store.put_knowledge(
            replace(current, confidence=next_confidence, validity=validity)
        )
        return application
