import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, CheckCircle2, Copy, Download, RefreshCcw, Save, ShieldAlert } from "lucide-react";
import { Navigate, useParams } from "react-router";
import { toast } from "sonner";
import { studioApi } from "../api";
import { Badge, Button, Card, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";
import { studioKeys, useArticle } from "../queries";

export function ArticleEditorPage() {
  const { articleId = "" } = useParams();
  const query = useArticle(articleId);
  const client = useQueryClient();
  const [longTitle, setLongTitle] = useState(""); const [longBody, setLongBody] = useState("");
  const [shortTitle, setShortTitle] = useState(""); const [shortBody, setShortBody] = useState("");
  const [instructions, setInstructions] = useState("");
  const [viewingVersion, setViewingVersion] = useState(0);
  useEffect(() => { const draft = query.data?.draft; if (!draft) return; setViewingVersion(query.data?.current_version || 0); setLongTitle(draft.long_title); setLongBody(draft.long_markdown); setShortTitle(draft.short_title); setShortBody(draft.short_markdown); }, [query.data?.current_version]);
  const refresh = () => client.invalidateQueries({ queryKey: studioKeys.article(articleId) });
  const save = useMutation({ mutationFn: () => studioApi.updateArticle(articleId, query.data!.current_version, { long_title: longTitle, long_markdown: longBody, short_title: shortTitle, short_markdown: shortBody }), onSuccess: async () => { toast.success("已保存为新版本"); await refresh(); }, onError: (error) => toast.error(error instanceof Error ? error.message : "保存失败") });
  const archive = useMutation({ mutationFn: () => studioApi.updateArticle(articleId, query.data!.current_version, { status: "archived" }), onSuccess: async () => { toast.success("文章已归档，所有历史版本仍保留"); await refresh(); }, onError: (error) => toast.error(error instanceof Error ? error.message : "归档失败") });
  const regenerate = useMutation({ mutationFn: (platform: string) => studioApi.regenerateArticle(articleId, query.data!.current_version, platform, instructions), onSuccess: async () => { toast.success("已生成新版本，原编辑版本仍保留"); await refresh(); }, onError: (error) => toast.error(error instanceof Error ? error.message : "重新生成失败") });
  async function copy(platform: "long" | "short") { await navigator.clipboard.writeText(platform === "long" ? `# ${longTitle}\n\n${longBody}` : `# ${shortTitle}\n\n${shortBody}`); toast.success("已复制 Markdown"); }
  async function download(platform: "long" | "short", format: "markdown" | "html" | "text") { const current = query.data?.draft; if (current && (longTitle !== current.long_title || longBody !== current.long_markdown || shortTitle !== current.short_title || shortBody !== current.short_markdown)) { toast.error("请先保存当前编辑，再通过隐私门导出"); return; } try { const value = await studioApi.exportArticle(articleId, platform, format); const blob = new Blob([value.content], { type: value.media_type }); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = value.filename; link.click(); URL.revokeObjectURL(url); } catch (error) { toast.error(error instanceof Error ? error.message : "导出被隐私门阻止"); } }
  async function loadVersion(version: number) { try { const value = await studioApi.article(articleId, version); if (!value.draft) return; setViewingVersion(version); setLongTitle(value.draft.long_title); setLongBody(value.draft.long_markdown); setShortTitle(value.draft.short_title); setShortBody(value.draft.short_markdown); } catch (error) { toast.error(error instanceof Error ? error.message : "版本加载失败"); } }
  if (query.isLoading) return <div className="page"><Skeleton className="h-64" /></div>;
  if (query.isError) return <div className="page"><LoadFailure onRetry={() => query.refetch()} /></div>;
  if (!query.data?.draft) return <Navigate to="/articles" replace />;
  const article = query.data;
  const draft = article.draft!;
  const unsupported = article.claims.filter((claim) => claim.status !== "supported");
  return <div className="page article-editor-page">
    <PageTitle eyebrow={`Article Studio · v${viewingVersion || article.current_version}`} title={article.title} detail="长短文共享事实大纲，但各自按平台结构生成；保存和重新生成都会创建新版本。" actions={<><select className="version-select" value={viewingVersion || article.current_version} onChange={(event) => loadVersion(Number(event.target.value))}>{article.versions.map((version) => <option key={version.version} value={version.version}>版本 {version.version} · {new Date(version.created_at).toLocaleString()}</option>)}</select><Button onClick={() => archive.mutate()} disabled={archive.isPending || article.status === "archived"}><Archive size={15} />{article.status === "archived" ? "已归档" : "归档"}</Button><Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} />另存为新版本</Button></>} />
    <div className="article-editor-grid">
      <Card className="draft-editor"><SectionTitle title="公众号长文" meta={`${longBody.length} 字符`} /><input className="draft-title" value={longTitle} onChange={(event) => setLongTitle(event.target.value)} /><textarea value={longBody} onChange={(event) => setLongBody(event.target.value)} /><footer><Button size="sm" onClick={() => copy("long")}><Copy size={14} />复制</Button><Button size="sm" onClick={() => download("long", "markdown")}><Download size={14} />Markdown</Button><Button size="sm" onClick={() => regenerate.mutate("long")}><RefreshCcw size={14} />仅重写长文</Button></footer></Card>
      <Card className="draft-editor"><SectionTitle title="小红书短文" meta={`${shortBody.length} 字符`} /><input className="draft-title" value={shortTitle} onChange={(event) => setShortTitle(event.target.value)} /><textarea value={shortBody} onChange={(event) => setShortBody(event.target.value)} /><footer><Button size="sm" onClick={() => copy("short")}><Copy size={14} />复制</Button><Button size="sm" onClick={() => download("short", "text")}><Download size={14} />纯文本</Button><Button size="sm" onClick={() => regenerate.mutate("short")}><RefreshCcw size={14} />仅重写短文</Button></footer>{draft.topics.length > 0 && <div className="topic-row">{draft.topics.map((topic) => <span key={topic}>{topic}</span>)}</div>}</Card>
    </div>
    <Card className="regenerate-box"><label className="field"><span>局部重写说明</span><input value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="例如：保留事实，把转折写得更具体" /></label><Button onClick={() => regenerate.mutate("both")} disabled={regenerate.isPending}><RefreshCcw size={15} />重新生成双稿</Button></Card>
    <Card><SectionTitle title="ClaimMap" meta={`${article.claims.length} 项关键结论`} />{unsupported.length > 0 && <div className="inline-warning"><ShieldAlert />{unsupported.length} 项结论缺少完整证据，确认前不应公开。</div>}<div className="claim-list">{article.claims.map((claim) => <article key={claim.id}><span>{claim.status === "supported" ? <CheckCircle2 /> : <ShieldAlert />}</span><div><header><Badge value={claim.status} /><small>{claim.platform}</small></header><p>{claim.claim}</p><footer>{claim.knowledge_ids.length} 条知识来源 · {claim.evidence_ids.length} 条验证证据</footer></div></article>)}</div></Card>
  </div>;
}
