from onep.studio.articles import ArticleStudio
from onep.studio.credentials import MemoryCredentialStore
from onep.studio.knowledge import KnowledgeService
from onep.studio.models import KnowledgeRecord
from onep.studio.store import StudioStore


class FakeArticleModel:
    def generate(self, profile, credential, prompt):
        assert credential == "secret"
        assert "/Users/private" not in prompt
        assert "secret@example.com" not in prompt
        assert "私有仓库" not in prompt
        knowledge_id = "knowledge-1"
        return {
            "long_title": "一次失败如何变成方法",
            "long_markdown": "背景、失败、转折、修复与复用经验。",
            "short_title": "这个坑别踩两次",
            "short_markdown": "具体问题、关键坑点、解决方式和结论。",
            "title_candidates": ["候选标题"], "topics": ["#工程复盘"],
            "claims": [{
                "platform": "both", "claim": "历史方法在新项目中有效",
                "knowledge_ids": [knowledge_id], "evidence_ids": ["evidence-1"],
            }, {
                "platform": "long", "claim": "模型声称还有一条证据",
                "knowledge_ids": [knowledge_id], "evidence_ids": ["fabricated"],
            }],
        }


def _record(project_id, *, validity="validated", title="缓存失败"):
    return KnowledgeRecord(
        id="knowledge-1" if validity == "validated" else f"knowledge-{validity}",
        type="failure", title=title, project_id=project_id,
        summary="secret@example.com 在 /Users/private/repo 遇到错误",
        root_cause="连接复用错误", final_fix="限定连接生命周期",
        validity=validity, confidence=0.9, generalizable=True,
        technology_stack=("python",), components=("cache",), tags=("timeout",),
        evidence_ids=("evidence-1",),
    )


def test_knowledge_context_is_bounded_sourced_and_excludes_invalid_records(tmp_path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("来源项目", "缓存系统", str(tmp_path / "repo"))
    target = store.create_project("目标项目", "修复缓存", str(tmp_path / "target"))
    knowledge = KnowledgeService(store)
    store.put_knowledge(_record(project["id"]))
    store.put_knowledge(_record(project["id"], validity="contradicted", title="错误旧结论"))

    context = knowledge.context(
        "缓存 timeout", target_project_id=target["id"], phase="technical_plan"
    )

    assert len(context["rendered"]) <= 6000
    assert "缓存失败" in context["rendered"]
    assert "错误旧结论" not in context["rendered"]
    assert project["id"] not in context["rendered"]
    assert "来源项目=[已泛化]" in context["rendered"]
    applications = store.knowledge_applications(target["id"])
    assert applications[0]["result"] == "pending"

    knowledge.feedback(
        "knowledge-1", target["id"], "feature-1", "technical_plan",
        "contradicted", "当前项目连接模型不同，未采用",
    )
    source = store.get_knowledge("knowledge-1")
    application = store.knowledge_applications(target["id"])[0]
    assert source["validity"] == "validated"
    assert source["confidence"] < 0.9
    assert application["adopted_as"] == "当前项目连接模型不同，未采用"


def test_article_studio_sanitizes_before_model_and_versions_drafts(tmp_path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("私有仓库", "技术项目", str(tmp_path / "repo"))
    knowledge = KnowledgeService(store)
    store.put_knowledge(_record(project["id"]))
    credentials = MemoryCredentialStore()
    studio = ArticleStudio(
        store, knowledge, model=FakeArticleModel(), credentials=credentials
    )
    profile = studio.save_model_profile({
        "name": "写作模型", "provider": "openai", "model": "test-model",
        "credential": "secret", "is_default": True,
    })
    assert profile["credential_configured"] is True
    assert "secret" not in str(profile)

    pack = studio.create_source_pack([project["id"]], ["knowledge-1"])
    serialized = str(pack["facts"])
    assert "secret@example.com" not in serialized
    assert "/Users/private" not in serialized
    assert pack["confirmed"] is False
    pack = store.confirm_source_pack(pack["id"], pack["revision"])
    article = studio.generate(
        {
            "topic": "私有仓库工程失败复盘",
            "audience": "secret@example.com /Users/private/brief",
        },
        pack["id"],
    )
    assert article["draft"]["long_markdown"] != article["draft"]["short_markdown"]
    assert article["claims"][0]["status"] == "supported"
    assert article["claims"][1]["status"] == "needs_confirmation"
    assert article["claims"][1]["evidence_ids"] == []

    edited = studio.update_draft(
        article["id"], article["current_version"], {"short_title": "用户编辑标题"}
    )
    assert edited["current_version"] == 2
    assert edited["draft"]["short_title"] == "用户编辑标题"
    assert [value["version"] for value in edited["versions"]] == [2, 1]

    archived = studio.update_draft(
        article["id"], edited["current_version"], {"status": "archived"}
    )
    assert archived["status"] == "archived"
    assert archived["current_version"] == 3
