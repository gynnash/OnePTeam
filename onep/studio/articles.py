"""Evidence-backed, privacy-filtered WeChat and Xiaohongshu article studio."""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Protocol

from onep.domain import Problem
from onep.studio.credentials import KeyringCredentialStore
from onep.studio.knowledge import KnowledgeService
from onep.studio.models import new_id
from onep.studio.product import _json_object
from onep.studio.privacy import sanitize_for_model
from onep.studio.store import StudioStore


class ArticleModel(Protocol):
    def generate(
        self, profile: dict[str, Any], credential: str, prompt: str
    ) -> dict[str, Any]: ...


class LiteLLMArticleModel:
    def generate(
        self, profile: dict[str, Any], credential: str, prompt: str
    ) -> dict[str, Any]:
        from litellm import completion

        parameters = {
            key: value for key, value in (profile.get("parameters") or {}).items()
            if key in {"temperature", "top_p", "max_tokens"}
        }
        provider = str(profile.get("provider") or "").strip().lower()
        model = str(profile["model"]).strip()
        if "/" not in model and provider and provider != "openai":
            prefix = "openai" if provider in {
                "openai-compatible", "openai_compatible"
            } else provider
            model = f"{prefix}/{model}"
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 OnePTeam 的中文技术文章编辑。只使用确认素材，"
                        "不能虚构事实、数据、失败或结果。表达口语化但保持技术准确。"
                        "只返回指定 JSON。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            **parameters,
        }
        if credential:
            kwargs["api_key"] = credential
        if profile.get("api_base"):
            kwargs["api_base"] = profile["api_base"]
        try:
            response = completion(**kwargs)
        except Exception as exc:
            raise Problem(
                "article_model_failed", "Article model request failed",
                sanitize_for_model(str(exc), max_chars=2000),
                actionable=True, suggested_actions=("test_article_model", "retry"),
            ) from exc
        return _json_object(response.choices[0].message.content or "")


class PrivacyScanner:
    SECRET_PATTERNS = (
        ("api_key", re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+")),
        ("bearer_token", re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]{12,}")),
        ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
        ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
        ("absolute_path", re.compile(r"(?<![\w.])(?:/Users|/home|/var|/private|[A-Z]:\\)[^\s`\"']+")),
        ("private_ip", re.compile(r"\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}\b")),
    )

    REPLACEMENTS = {
        "api_key": "[已移除凭据]", "bearer_token": "[已移除凭据]",
        "openai_key": "[已移除凭据]", "email": "[已隐藏邮箱]",
        "absolute_path": "[本地路径]", "private_ip": "[内部地址]",
    }

    def scan(self, text: str, custom_terms: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
        risks = []
        for kind, pattern in self.SECRET_PATTERNS:
            for match in pattern.finditer(text or ""):
                risks.append(
                    {"type": kind, "start": match.start(), "end": match.end(),
                     "preview": match.group(0)[:40]}
                )
        for term in custom_terms:
            if term and term.lower() in (text or "").lower():
                risks.append({"type": "custom", "term": term, "preview": term[:40]})
        return risks

    def sanitize(
        self,
        text: str,
        *,
        project_names: list[str] | tuple[str, ...] = (),
        custom_replacements: dict[str, str] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
        original = text or ""
        risks = self.scan(original, tuple((custom_replacements or {}).keys()))
        sanitized = original
        replacements: dict[str, str] = {}
        for kind, pattern in self.SECRET_PATTERNS:
            sanitized, count = pattern.subn(self.REPLACEMENTS[kind], sanitized)
            if count:
                replacements[kind] = self.REPLACEMENTS[kind]
        for index, name in enumerate(project_names, start=1):
            if name and name in sanitized:
                alias = f"项目{chr(64 + min(index, 26))}"
                sanitized = sanitized.replace(name, alias)
                replacements[name] = alias
        for source, target in (custom_replacements or {}).items():
            if source:
                sanitized = re.sub(re.escape(source), target or "[已泛化]", sanitized, flags=re.I)
                replacements[source] = target or "[已泛化]"
        return sanitized, risks, replacements


class ArticleStudio:
    def __init__(
        self,
        store: StudioStore,
        knowledge: KnowledgeService,
        *,
        model: ArticleModel | None = None,
        credentials=None,
        scanner: PrivacyScanner | None = None,
    ) -> None:
        self.store = store
        self.knowledge = knowledge
        self.model = model or LiteLLMArticleModel()
        self.credentials = credentials or KeyringCredentialStore()
        self.scanner = scanner or PrivacyScanner()

    def save_model_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ("name", "provider", "model")
        missing = [key for key in required if not str(payload.get(key) or "").strip()]
        if missing:
            raise Problem("invalid_article_model", "Article model fields are required", ", ".join(missing))
        value = dict(payload)
        profile_id = str(value.get("id") or new_id("article_model"))
        value["id"] = profile_id
        secret = str(value.pop("credential", "") or "")
        if secret:
            reference = str(value.get("credential_ref") or profile_id)
            self.credentials.set(reference, secret)
            value["credential_ref"] = reference
            value["credential_configured"] = True
        elif value.get("id"):
            try:
                current = self.store.get_article_model_profile(profile_id)
            except Problem:
                current = None
            if current:
                value.setdefault("credential_ref", current["credential_ref"])
                value.setdefault("credential_configured", current["credential_configured"])
        return self.store.save_article_model_profile(value)

    def delete_model_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.store.get_article_model_profile(profile_id)
        deleted = self.store.delete_article_model_profile(profile_id)
        if deleted.get("deleted"):
            self.credentials.delete(profile["credential_ref"])
        return deleted

    def test_model_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.store.get_article_model_profile(profile_id)
        credential = self.credentials.get(profile["credential_ref"])
        result = self.model.generate(
            profile,
            credential,
            '只返回 {"long_title":"OK","long_markdown":"OK",'
            '"short_title":"OK","short_markdown":"OK",'
            '"title_candidates":[],"topics":[],"claims":[]}',
        )
        return {"connected": True, "response": str(result.get("long_title") or "")[:80]}

    def source_suggestions(
        self, project_ids: list[str], query: str = "", limit: int = 20
    ) -> dict[str, Any]:
        if not project_ids:
            raise Problem("project_required", "Select at least one project")
        projects = [self.store.get_project(project_id) for project_id in project_ids]
        seed_records = [
            record for project_id in project_ids
            for record in self.store.knowledge_rows(project_id)
        ]
        seed_text = " ".join(
            [query, *(project["idea"] for project in projects),
             *(record.get("summary") or record["title"] for record in seed_records)]
        )
        related = self.knowledge.search(seed_text, limit=min(max(limit, 1), 50))
        selected_ids = {record["id"] for record in seed_records}
        records = [*seed_records, *(r for r in related if r["id"] not in selected_ids)]
        related_project_ids = list(dict.fromkeys(
            [*project_ids, *(record["project_id"] for record in related)]
        ))
        related_projects = [
            self.store.get_project(project_id) for project_id in related_project_ids
        ]
        return {
            "projects": [
                {
                    **project,
                    "relation_reason": (
                        "用户选择的起始项目" if project["id"] in project_ids
                        else "包含相似问题、技术栈或被复用的知识记录"
                    ),
                }
                for project in related_projects
            ],
            "knowledge": records[:limit],
        }

    def create_source_pack(
        self,
        project_ids: list[str],
        knowledge_ids: list[str],
        *,
        replacements: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        projects = [self.store.get_project(project_id) for project_id in project_ids]
        project_names = [project["name"] for project in projects]
        records = [self.store.get_knowledge(value) for value in knowledge_ids]
        facts = []
        all_risks = []
        applied_replacements: dict[str, str] = {}
        for record in records:
            raw = json.dumps(
                {
                    "title": record["title"], "type": record["type"],
                    "summary": record.get("summary"),
                    "problem": record.get("problem_context"),
                    "decision": record.get("selected"), "reason": record.get("reason"),
                    "failure": record.get("failure_symptom"),
                    "root_cause": record.get("root_cause"),
                    "final_fix": record.get("final_fix"),
                    "prevention": record.get("prevention"),
                    "validity": record.get("validity"),
                },
                ensure_ascii=False,
            )
            sanitized, risks, used = self.scanner.sanitize(
                raw, project_names=project_names, custom_replacements=replacements,
            )
            facts.append(
                {
                    "knowledge_id": record["id"],
                    "source_project_id": record["project_id"],
                    "content": json.loads(sanitized),
                    "evidence_ids": record.get("evidence_ids") or [],
                    "validity": record["validity"],
                }
            )
            all_risks.extend({**risk, "knowledge_id": record["id"]} for risk in risks)
            applied_replacements.update(used)
        return self.store.create_source_pack(
            {
                "project_ids": project_ids, "knowledge_ids": knowledge_ids,
                "facts": facts, "risks": all_risks,
                "replacements": applied_replacements,
            }
        )

    def generate(
        self,
        brief: dict[str, Any],
        source_pack_id: str,
        *,
        model_profile_id: str = "",
    ) -> dict[str, Any]:
        pack = self.store.get_source_pack(source_pack_id)
        if not pack["confirmed"]:
            raise Problem(
                "source_pack_not_confirmed", "Confirm the sanitized source pack first",
                actionable=True, suggested_actions=("review_sources",),
            )
        profile = self.store.get_article_model_profile(model_profile_id)
        credential = self.credentials.get(profile["credential_ref"])
        article = self.store.create_article(brief, source_pack_id, profile["id"])
        prompt = self._prompt(self._sanitized_brief(brief, pack), pack)
        generated = self.model.generate(profile, credential, prompt)
        draft, claims = self._validate_generation(generated, pack)
        self._assert_export_safe(draft)
        return self.store.add_article_draft(article["id"], draft, claims)

    def update_draft(
        self,
        article_id: str,
        expected_version: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        article = self.store.get_article(article_id)
        if article["current_version"] != expected_version:
            raise Problem("revision_conflict", "Article draft changed elsewhere")
        draft = dict(article["draft"] or {})
        allowed = {
            "long_title", "long_markdown", "short_title", "short_markdown",
            "title_candidates", "topics", "status",
        }
        if set(patch) - allowed:
            raise Problem("invalid_article_patch", "Unsupported article fields")
        requested_status = str(patch.get("status") or "edited")
        if requested_status not in {"edited", "archived"}:
            raise Problem("invalid_article_status", "Invalid article status")
        draft.update(patch)
        draft["status"] = requested_status
        draft["generation"] = {"source": "user_edit", "base_version": expected_version}
        self._assert_export_safe(draft)
        return self.store.add_article_draft(article_id, draft, article["claims"])

    def regenerate(
        self,
        article_id: str,
        expected_version: int,
        *,
        platform: str = "both",
        instructions: str = "",
    ) -> dict[str, Any]:
        article = self.store.get_article(article_id)
        if article["current_version"] != expected_version:
            raise Problem("revision_conflict", "Article draft changed elsewhere")
        pack = self.store.get_source_pack(article["source_pack_id"])
        profile = self.store.get_article_model_profile(article["model_profile_id"])
        credential = self.credentials.get(profile["credential_ref"])
        regeneration_brief = {
            **article["brief"], "regenerate_platform": platform,
            "additional_instructions": instructions,
            "current_draft": article["draft"],
        }
        prompt = self._prompt(self._sanitized_brief(regeneration_brief, pack), pack)
        generated = self.model.generate(profile, credential, prompt)
        next_draft, claims = self._validate_generation(generated, pack)
        current = article["draft"]
        if platform == "long":
            next_draft.update(
                short_title=current["short_title"],
                short_markdown=current["short_markdown"], topics=current["topics"],
            )
            claims = [
                *(
                    claim for claim in claims
                    if claim.get("platform") != "short"
                ),
                *(
                    claim for claim in article["claims"]
                    if claim.get("platform") == "short"
                ),
            ]
        elif platform == "short":
            next_draft.update(
                long_title=current["long_title"],
                long_markdown=current["long_markdown"],
            )
            claims = [
                *(
                    claim for claim in claims
                    if claim.get("platform") != "long"
                ),
                *(
                    claim for claim in article["claims"]
                    if claim.get("platform") == "long"
                ),
            ]
        elif platform != "both":
            raise Problem("invalid_article_platform", "Invalid article platform", platform)
        self._assert_export_safe(next_draft)
        return self.store.add_article_draft(article_id, next_draft, claims)

    def export(self, article_id: str, platform: str, format_name: str) -> dict[str, str]:
        article = self.store.get_article(article_id)
        draft = article["draft"] or {}
        if platform not in {"long", "short"}:
            raise Problem("invalid_article_platform", "Select long or short article")
        title = str(draft.get(f"{platform}_title") or article["title"])
        markdown = str(draft.get(f"{platform}_markdown") or "")
        self._assert_export_safe({"content": markdown, "title": title})
        if format_name == "markdown":
            content, extension, media_type = f"# {title}\n\n{markdown}\n", "md", "text/markdown"
        elif format_name == "text":
            content = re.sub(r"[#*_`>]", "", f"{title}\n\n{markdown}")
            extension, media_type = "txt", "text/plain"
        elif format_name == "html":
            content = self._markdown_html(title, markdown)
            extension, media_type = "html", "text/html"
        else:
            raise Problem("invalid_export_format", "Unsupported article export", format_name)
        filename = re.sub(r"[^\w一-鿿.-]+", "-", title).strip("-")[:80] or "article"
        return {
            "content": content, "filename": f"{filename}.{extension}",
            "media_type": media_type,
        }

    def _validate_generation(
        self, value: dict[str, Any], pack: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        required = ("long_title", "long_markdown", "short_title", "short_markdown")
        missing = [key for key in required if not str(value.get(key) or "").strip()]
        if missing:
            raise Problem("article_model_invalid_output", "Article model omitted fields", ", ".join(missing))
        allowed_knowledge = set(pack["knowledge_ids"])
        allowed_evidence = {
            str(evidence_id)
            for fact in pack.get("facts") or ()
            for evidence_id in fact.get("evidence_ids") or ()
        }
        claims = []
        for claim in value.get("claims") or ():
            if not isinstance(claim, dict) or not str(claim.get("claim") or "").strip():
                continue
            knowledge_ids = [str(v) for v in claim.get("knowledge_ids") or ()]
            requested_evidence = [str(v) for v in claim.get("evidence_ids") or ()]
            evidence_ids = [
                value for value in requested_evidence if value in allowed_evidence
            ]
            supported = (
                bool(knowledge_ids)
                and set(knowledge_ids).issubset(allowed_knowledge)
                and len(evidence_ids) == len(requested_evidence)
            )
            claims.append(
                {
                    "platform": str(claim.get("platform") or "both"),
                    "claim": str(claim["claim"]), "knowledge_ids": knowledge_ids,
                    "evidence_ids": evidence_ids,
                    "status": "supported" if supported else "needs_confirmation",
                }
            )
        draft = {
            "long_title": str(value["long_title"]).strip(),
            "long_markdown": str(value["long_markdown"]).strip(),
            "short_title": str(value["short_title"]).strip(),
            "short_markdown": str(value["short_markdown"]).strip(),
            "title_candidates": [str(v) for v in value.get("title_candidates") or ()][:5],
            "topics": [str(v) for v in value.get("topics") or ()][:12],
            "generation": {"shared_fact_outline": True}, "status": "draft",
        }
        return draft, claims

    def _assert_export_safe(self, value: dict[str, Any]) -> None:
        text = json.dumps(value, ensure_ascii=False)
        risks = self.scanner.scan(text)
        if risks:
            raise Problem(
                "article_privacy_risk", "Article contains sensitive information",
                json.dumps(risks[:10], ensure_ascii=False), actionable=True,
                suggested_actions=("edit_draft", "regenerate"),
            )

    def _sanitized_brief(
        self, brief: dict[str, Any], pack: dict[str, Any]
    ) -> dict[str, Any]:
        projects = [
            self.store.get_project(project_id)
            for project_id in pack.get("project_ids") or ()
        ]
        serialized = json.dumps(brief, ensure_ascii=False, default=str)
        sanitized, _risks, _used = self.scanner.sanitize(
            serialized,
            project_names=[project["name"] for project in projects],
            custom_replacements=dict(pack.get("replacements") or {}),
        )
        try:
            value = json.loads(sanitized)
        except json.JSONDecodeError:
            value = {"instructions": sanitized}
        return value if isinstance(value, dict) else {"brief": value}

    @staticmethod
    def _prompt(brief: dict[str, Any], pack: dict[str, Any]) -> str:
        shape = {
            "long_title": "", "long_markdown": "2500-4500 字公众号文章",
            "short_title": "", "short_markdown": "600-1000 字小红书文章",
            "title_candidates": [""], "topics": ["#技术"],
            "claims": [{
                "platform": "both", "claim": "", "knowledge_ids": ["knowledge_id"],
                "evidence_ids": [],
            }],
        }
        prompt = f"""根据同一份已确认事实素材，同时生成两种中文口语化技术文章。
文章 Brief：{json.dumps(brief, ensure_ascii=False)}
已确认、已脱敏的事实素材：{json.dumps(pack['facts'], ensure_ascii=False)}

公众号长文目标 2500-4500 中文字，包含背景、错误尝试、关键转折、解决方法和可复用经验。
小红书短文目标 600-1000 中文字，使用强开场、具体坑点、解决方式和行动结论；不是长文截断。
两篇文章共享同一事实大纲。正文不得出现内部 knowledge ID、Wikilink 或来源项目私有名称。
每个关键事实在 claims 中关联素材里的 knowledge_id；没有来源的观点标记空 knowledge_ids。
只返回 JSON：{json.dumps(shape, ensure_ascii=False)}"""
        return sanitize_for_model(prompt, max_chars=60_000)

    @staticmethod
    def _markdown_html(title: str, markdown: str) -> str:
        lines = []
        in_list = False
        for raw in markdown.splitlines():
            text = raw.strip()
            if text.startswith("### "):
                if in_list:
                    lines.append("</ul>")
                    in_list = False
                lines.append(f"<h3>{escape(text[4:])}</h3>")
            elif text.startswith("## "):
                if in_list:
                    lines.append("</ul>")
                    in_list = False
                lines.append(f"<h2>{escape(text[3:])}</h2>")
            elif text.startswith("- "):
                if not in_list:
                    lines.append("<ul>")
                    in_list = True
                lines.append(f"<li>{escape(text[2:])}</li>")
            elif text:
                if in_list:
                    lines.append("</ul>")
                    in_list = False
                lines.append(f"<p>{escape(text)}</p>")
        if in_list:
            lines.append("</ul>")
        return (
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            f"<title>{escape(title)}</title><article><h1>{escape(title)}</h1>"
            + "".join(lines) + "</article></html>"
        )
