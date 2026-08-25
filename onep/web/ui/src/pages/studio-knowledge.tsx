import { FormEvent, useState } from "react";
import { ArrowRight, BookOpen, CheckCircle2, Network, Search, Sparkles } from "lucide-react";
import { Link } from "react-router";
import { Badge, Button, Card, Empty, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";
import { useStudioKnowledge } from "../queries";

export function StudioKnowledgePage() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const knowledge = useStudioKnowledge(query);
  const records = knowledge.data?.records || [];
  const clusters = records.reduce<Record<string, number>>((result, record) => {
    for (const component of record.components.length ? record.components : [record.type]) result[component] = (result[component] || 0) + 1;
    return result;
  }, {});
  return <div className="page knowledge-page">
    <PageTitle eyebrow="Engineering Memory" title="知识" detail="记录真实决策、失败、根因、修复与跨项目复用结果；历史知识是带来源的先验，不是全局真理。" actions={<Link className="button button-primary button-md" to="/articles"><Sparkles size={16} />从知识生成文章</Link>} />
    <Card className="knowledge-search-card">
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); setQuery(draft.trim()); }}><Search size={18} /><input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索问题、错误签名、技术栈、组件或决策…" /><Button type="submit">搜索</Button></form>
      <div className="knowledge-principles"><span><CheckCircle2 />观察事实、模型推断、人工决定分开保存</span><span><Network />每次跨项目应用都有结果反馈</span></div>
    </Card>
    <div className="knowledge-layout">
      <aside><Card><SectionTitle title="问题簇" meta={`${Object.keys(clusters).length} 组`} />{Object.entries(clusters).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([name, count]) => <button key={name} onClick={() => { setDraft(name); setQuery(name); }}><span>{name}</span><b>{count}</b></button>)}</Card></aside>
      <Card><SectionTitle title={query ? `“${query}” 的结果` : "全部知识记录"} meta={`${records.length} 条`} />
        {knowledge.isLoading ? <Skeleton className="h-64" /> : knowledge.isError ? <LoadFailure onRetry={() => knowledge.refetch()} /> : records.length ? <div className="knowledge-records">{records.map((record) => <article key={record.id}>
          <header><Badge value={record.validity} /><span>{record.type}</span><time>{new Date(record.updated_at).toLocaleDateString()}</time></header>
          <h2>{record.title}</h2><p>{record.summary}</p>
          {record.root_cause && <div><b>根因</b><span>{record.root_cause}</span></div>}
          {record.final_fix && <div><b>最终修复</b><span>{record.final_fix}</span></div>}
          <footer><span>可信度 {Math.round(record.confidence * 100)}%</span>{record.generalizable && <span>可迁移</span>}{record.tags.map((tag) => <small key={tag}>#{tag}</small>)}</footer>
        </article>)}</div> : <Empty icon={<BookOpen />} title="没有匹配的知识" detail="执行边界产生的原始事件不会因为模型提炼失败而丢失。" />}
      </Card>
    </div>
    <Link className="article-cta" to="/articles"><div><Sparkles /><span><b>把工程复利变成公开内容</b><small>单项目或多项目生成公众号长文和小红书短文</small></span></div><ArrowRight /></Link>
  </div>;
}
