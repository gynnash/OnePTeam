import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, FileText, LockKeyhole, Plus, Sparkles } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { toast } from "sonner";
import { KnowledgeRecord, StudioProject, studioApi } from "../api";
import { Badge, Button, Card, Empty, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";
import { studioKeys, useArticleModels, useArticles, useStudioProjects } from "../queries";

type SourcePack = { id: string; revision: number; confirmed: boolean; facts: Array<Record<string, unknown>>; risks: Array<Record<string, unknown>>; replacements: Record<string, string> };

export function ArticlesPage() {
  const projectsQuery = useStudioProjects();
  const articles = useArticles();
  const models = useArticleModels();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"projects" | "records" | "privacy" | "brief">("projects");
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<{ projects: StudioProject[]; knowledge: KnowledgeRecord[] } | null>(null);
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([]);
  const [pack, setPack] = useState<SourcePack | null>(null);
  const [topic, setTopic] = useState("");
  const [angle, setAngle] = useState("");
  const [audience, setAudience] = useState("有实战经验的软件开发者");
  const [tone, setTone] = useState("口语化、诚实、有具体经验");
  const [profileId, setProfileId] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const project = searchParams.get("project") || "";
    if (project && !projectIds.length) { setProjectIds([project]); setOpen(true); }
  }, [searchParams]);

  const fail = (error: unknown) => toast.error(error instanceof Error ? error.message : "操作失败");
  async function recommend() {
    if (!projectIds.length) return;
    setBusy(true);
    try {
      const value = await studioApi.sourceSuggestions(projectIds, topic);
      setSuggestions(value); setKnowledgeIds(value.knowledge.map((record) => record.id)); setStep("records");
    } catch (error) { fail(error); } finally { setBusy(false); }
  }
  async function preparePack() {
    setBusy(true);
    try { setPack(await studioApi.createSourcePack(projectIds, knowledgeIds) as SourcePack); setStep("privacy"); }
    catch (error) { fail(error); } finally { setBusy(false); }
  }
  async function confirmPack() {
    if (!pack) return;
    setBusy(true);
    try { setPack(await studioApi.confirmSourcePack(pack.id, pack.revision) as SourcePack); setStep("brief"); }
    catch (error) { fail(error); } finally { setBusy(false); }
  }
  async function generate(event: FormEvent) {
    event.preventDefault(); if (!pack) return;
    setBusy(true);
    try {
      const article = await studioApi.generateArticle({ topic, angle, audience, tone, project_ids: projectIds, knowledge_ids: knowledgeIds }, pack.id, profileId);
      await client.invalidateQueries({ queryKey: studioKeys.articles });
      toast.success("长文与短文已从同一事实大纲生成"); navigate(`/articles/${article.id}`);
    } catch (error) { fail(error); } finally { setBusy(false); }
  }
  function resetWizard() { setOpen(true); setStep("projects"); setProjectIds([]); setSuggestions(null); setKnowledgeIds([]); setPack(null); }

  return <div className="page articles-page">
    <PageTitle eyebrow="Article Studio" title="文章" detail="把经过验证的真实工程过程，转成可编辑的公众号长文与小红书短文。" actions={<Button variant="primary" onClick={resetWizard}><Plus size={16} />生成文章</Button>} />
    {open && <Card className="article-wizard">
      <div className="wizard-steps">{[["projects", "选择项目"], ["records", "选择知识"], ["privacy", "隐私确认"], ["brief", "生成草稿"]].map(([id, label], index) => <span key={id} className={step === id ? "active" : ""}><i>{index + 1}</i>{label}</span>)}</div>
      {step === "projects" && <div><SectionTitle title="从一个或多个项目开始" meta="系统会推荐真正相关的项目与记录" /><div className="source-projects">{projectsQuery.data?.projects.map((project) => <label key={project.id}><input type="checkbox" checked={projectIds.includes(project.id)} onChange={() => setProjectIds((value) => value.includes(project.id) ? value.filter((id) => id !== project.id) : [...value, project.id])} /><span><b>{project.name}</b><small>{project.idea}</small></span></label>)}</div><div className="wizard-actions"><Button variant="ghost" onClick={() => setOpen(false)}>取消</Button><Button variant="primary" disabled={!projectIds.length || busy} onClick={recommend}>{busy ? "正在关联…" : "推荐相关素材"}<ArrowRight size={14} /></Button></div></div>}
      {step === "records" && suggestions && <div><SectionTitle title="确认关联项目和知识记录" meta={`${projectIds.length} 个项目 · ${knowledgeIds.length} 条知识`} /><p className="section-explainer">系统按问题、技术栈、错误签名和历史复用关系推荐；你可以增加或删除任何项目与记录。</p><div className="related-projects">{suggestions.projects.map((project) => <label key={project.id}><input type="checkbox" checked={projectIds.includes(project.id)} onChange={() => setProjectIds((value) => value.includes(project.id) ? value.filter((id) => id !== project.id) : [...value, project.id])} /><span><b>{project.name}</b><small>{String((project as StudioProject & { relation_reason?: string }).relation_reason || "相关项目")}</small></span></label>)}</div><div className="source-records">{suggestions.knowledge.map((record) => <label key={record.id}><input type="checkbox" checked={knowledgeIds.includes(record.id)} onChange={() => setKnowledgeIds((value) => value.includes(record.id) ? value.filter((id) => id !== record.id) : [...value, record.id])} /><span><header><Badge value={record.validity} /><b>{record.title}</b></header><small>{record.summary}</small></span></label>)}</div><div className="wizard-actions"><Button onClick={() => setStep("projects")}>上一步</Button><Button variant="primary" disabled={!projectIds.length || !knowledgeIds.length || busy} onClick={preparePack}>生成脱敏素材包</Button></div></div>}
      {step === "privacy" && pack && <div><SectionTitle title="确认脱敏素材包" meta={`${pack.facts.length} 项事实`} /><div className="privacy-summary"><LockKeyhole /><div><b>脱敏已在模型调用前完成</b><p>凭据、邮箱、绝对路径、内部网络地址和项目名已移除或泛化。</p></div></div>{pack.risks.length > 0 && <div className="risk-list"><b>已发现并处理 {pack.risks.length} 个原始风险</b>{pack.risks.slice(0, 8).map((risk, index) => <span key={index}>{String(risk.type)} · {String(risk.preview || "已替换")}</span>)}</div>}<div className="fact-preview">{pack.facts.map((fact, index) => <article key={index}><span>事实 {index + 1}</span><pre>{JSON.stringify(fact.content, null, 2)}</pre></article>)}</div><div className="wizard-actions"><Button onClick={() => setStep("records")}>上一步</Button><Button variant="primary" disabled={busy} onClick={confirmPack}><Check size={14} />确认素材可发送</Button></div></div>}
      {step === "brief" && <form className="article-brief" onSubmit={generate}><SectionTitle title="定义文章叙事" meta="同时生成两种平台稿件" /><div className="field-grid"><label className="field"><span>主题</span><input required value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：一次缓存雪崩如何变成团队方法" /></label><label className="field"><span>文章模型</span><select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">默认 Profile</option>{models.data?.profiles.filter((profile) => profile.active).map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.model}</option>)}</select></label><label className="field"><span>叙事角度</span><input value={angle} onChange={(event) => setAngle(event.target.value)} placeholder="失败如何形成可迁移的方法" /></label><label className="field"><span>目标读者</span><input value={audience} onChange={(event) => setAudience(event.target.value)} /></label></div><label className="field"><span>语气</span><input value={tone} onChange={(event) => setTone(event.target.value)} /></label>{!models.data?.profiles.some((profile) => profile.active) && <p className="inline-warning">还没有可用文章模型。请先前往 <Link to="/settings">设置</Link> 配置。</p>}<div className="wizard-actions"><Button type="button" onClick={() => setStep("privacy")}>上一步</Button><Button variant="primary" type="submit" disabled={busy || !topic.trim() || !models.data?.profiles.some((profile) => profile.active)}><Sparkles size={15} />{busy ? "正在生成双稿…" : "生成长文和短文"}</Button></div></form>}
    </Card>}
    <Card><SectionTitle title="文章草稿" meta={`${articles.data?.articles.length || 0} 篇`} />{articles.isLoading ? <Skeleton className="h-64" /> : articles.isError ? <LoadFailure onRetry={() => articles.refetch()} /> : articles.data?.articles.length ? <div className="article-grid">{articles.data.articles.map((article) => <Link key={article.id} to={`/articles/${article.id}`}><span className="article-platform"><FileText />双平台</span><h2>{article.title}</h2><p>{String(article.brief.angle || article.brief.topic || "工程复盘")}</p><footer><Badge value={article.status} /><span>v{article.current_version}</span><ArrowRight size={15} /></footer></Link>)}</div> : <Empty icon={<FileText />} title="还没有文章草稿" detail="选择一个项目开始，系统也可以自动推荐相关项目形成跨项目叙事。" action={<Button onClick={resetWizard}>生成第一篇</Button>} />}</Card>
  </div>;
}
