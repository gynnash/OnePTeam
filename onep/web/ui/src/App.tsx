import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { api, Candidate, Job, LogEntry, Project, RunDetail } from './api';

type Route = { page: 'projects' | 'workbench'; project?: string };
type Tab = 'overview' | 'requirement' | 'plan' | 'execution' | 'verification' | 'changes' | 'knowledge' | 'settings';

const tabs: Array<[Tab, string]> = [
  ['overview', '概览'], ['requirement', '需求'], ['plan', '计划'], ['execution', '执行'],
  ['verification', '验证'], ['changes', '变更'], ['knowledge', '知识'], ['settings', '设置'],
];

function route(): Route {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  return parts[0] === 'project' && parts[1]
    ? { page: 'workbench', project: decodeURIComponent(parts[1]) }
    : { page: 'projects' };
}

function go(next: Route) {
  location.hash = next.page === 'workbench' ? `/project/${encodeURIComponent(next.project || '')}` : '/';
}

function Status({ value }: { value: string }) {
  return <span className={`status status-${value || 'unknown'}`}><i />{value || 'unknown'}</span>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

function ProjectList({ open }: { open: (project: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [workflow, setWorkflow] = useState<'build' | 'analyze' | 'optimize'>('build');
  const [requirement, setRequirement] = useState('');
  const [name, setName] = useState('');
  const [source, setSource] = useState('');

  const refresh = () => Promise.all([api.projects(), api.jobs()])
    .then(([projectData, jobData]) => { setProjects(projectData.projects); setJobs(jobData.jobs); })
    .catch(e => setError(e.message)).finally(() => setLoading(false));
  useEffect(() => { refresh(); const timer = setInterval(refresh, 5000); return () => clearInterval(timer); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (workflow === 'build' ? !requirement.trim() : !source.trim()) return;
    setCreating(true); setError(''); setNotice('');
    try {
      const actionId = crypto.randomUUID();
      if (workflow === 'build') {
        const result = await api.create({ requirement, name: name || undefined, workspace_path: source || undefined }, actionId);
        open(result.project.id);
      } else {
        const capability = workflow === 'analyze' ? 'analysis.start' : 'optimization.start';
        const result = await api.startWorkflow(capability, {
          source, name: name || undefined, max_rounds: workflow === 'optimize' ? 5 : undefined,
        }, actionId);
        setNotice(`任务已进入队列（${result.job_id.slice(0, 8)}）。项目生成后会自动出现在下方。`);
        setRequirement('');
      }
    } catch (e) { setError((e as Error).message); }
    finally { setCreating(false); }
  }

  const running = projects.filter(p => p.harness?.status === 'running' || p.status === 'running').length;
  const completed = projects.filter(p => p.harness?.status === 'completed' || p.status === 'completed').length;
  return <>
    <section className="hero">
      <div><p className="eyebrow">AUTONOMOUS SOFTWARE TEAM</p><h1>从一句话，到可验证的软件</h1>
      <p>描述目标，OnePTeam 会完成需求扩展、架构设计、实现、测试与交付。</p></div>
      <div className="hero-stats"><b>{projects.length}</b><span>项目</span><b>{running}</b><span>运行中</span><b>{completed}</b><span>已完成</span></div>
    </section>
    <section className="composer panel">
      <div className="section-title"><div><span className="step-number">01</span><h2>开始工作</h2></div><span>⌘ Enter 启动</span></div>
      <form onSubmit={submit}>
        <div className="workflow-picker">
          <button type="button" className={workflow === 'build' ? 'active' : ''} onClick={() => setWorkflow('build')}>构建应用</button>
          <button type="button" className={workflow === 'analyze' ? 'active' : ''} onClick={() => setWorkflow('analyze')}>分析代码</button>
          <button type="button" className={workflow === 'optimize' ? 'active' : ''} onClick={() => setWorkflow('optimize')}>自动优化</button>
        </div>
        <textarea value={requirement} onChange={e => setRequirement(e.target.value)}
          onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') e.currentTarget.form?.requestSubmit(); }}
          placeholder={workflow === 'build' ? '例如：创建一个能自动聚合技术动态并生成结构化周报的研究 Agent…' : '补充本次分析或优化的目标（可选）…'} />
        <div className="form-row">
          <label>项目名（可选）<input value={name} onChange={e => setName(e.target.value)} placeholder="自动生成" /></label>
          <label>{workflow === 'build' ? '已有 Git 目录（可选）' : 'Git 目录或仓库地址'}<input value={source} onChange={e => setSource(e.target.value)} placeholder="/path/to/repository" /></label>
          <button className="primary" disabled={creating || (workflow === 'build' ? !requirement.trim() : !source.trim())}>{creating ? '正在排队…' : workflow === 'build' ? '开始构建 →' : '开始执行 →'}</button>
        </div>
      </form>
      {error && <div className="notice error">{error}</div>}
      {notice && <div className="notice success">{notice}</div>}
    </section>
    {jobs.length > 0 && <section className="jobs panel">
      <div className="section-heading"><div><p className="eyebrow">ACTIVITY</p><h2>后台任务</h2></div><span>最近 {jobs.length} 项</span></div>
      <div className="job-list">{jobs.map(job => <details className="job" key={job.id}>
        <summary><Status value={job.status} /><b>{job.capability_id}</b><span>{job.id.slice(0, 8)}</span></summary>
        <pre>{JSON.stringify(job.error && Object.keys(job.error).length ? job.error : job.result, null, 2)}</pre>
      </details>)}</div>
    </section>}
    <section className="projects-section">
      <div className="section-heading"><div><p className="eyebrow">WORKSPACES</p><h2>项目</h2></div><button onClick={refresh}>刷新</button></div>
      {loading ? <Empty>正在读取项目…</Empty> : projects.length === 0 ? <Empty>还没有项目。先从上方描述一个目标。</Empty> :
      <div className="project-grid">{projects.map(project => {
        const run = project.harness;
        return <button className="project-card" key={project.id} onClick={() => open(project.id)}>
          <div className="project-card-top"><span className="project-icon">{project.name.slice(0, 2).toUpperCase()}</span><Status value={run?.status || project.status} /></div>
          <h3>{project.name}</h3><p>{project.requirement || run?.goal || '暂无需求摘要'}</p>
          <div className="project-meta"><span>{run?.stage || project.current_stage || '尚未开始'}</span><span>{run ? `第 ${run.iteration} 轮` : project.mode}</span></div>
          <div className="progress"><i style={{ width: run?.status === 'completed' ? '100%' : run?.status === 'running' ? '55%' : '12%' }} /></div>
        </button>;
      })}</div>}
    </section>
  </>;
}

function Workbench({ name: projectRef, back }: { name: string; back: () => void }) {
  const [tab, setTab] = useState<Tab>('overview');
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [notes, setNotes] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  async function refresh() {
    try {
      const listed = await api.projects();
      setProject(listed.projects.find(item => item.id === projectRef || item.name === projectRef) || null);
      const [nextDetail, logData, candidateData, noteData] = await Promise.all([
        api.detail(projectRef).catch(() => null), api.logs(projectRef).catch(() => ({ entries: [], next_offset: 0 })),
        api.candidates(projectRef).catch(() => ({ candidates: [] })), api.notes(projectRef).catch(() => ({ notes: [] })),
      ]);
      setDetail(nextDetail); setLogs(logData.entries); setCandidates(candidateData.candidates); setNotes(noteData.notes); setError('');
    } catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 3000); return () => clearInterval(timer); }, [projectRef]);
  useEffect(() => {
    if (!project?.id) return;
    const stream = new EventSource(`/api/v1/events/stream?project_id=${encodeURIComponent(project.id)}`);
    stream.onmessage = event => {
      const payload = JSON.parse(event.data) as { type?: string };
      if (payload.type !== 'heartbeat') refresh();
    };
    return () => stream.close();
  }, [project?.id]);

  const latestQuality = detail?.quality_history.at(-1) || {};
  const activeStage = detail?.stage || project?.current_stage || 'init';
  const displayEvents = useMemo(() => logs.slice(-120).reverse(), [logs]);

  async function action(label: string, work: () => Promise<unknown>) {
    setBusy(label); setError('');
    try { await work(); await refresh(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  }

  const displayName = project?.name || detail?.project_name || projectRef;
  return <div className="workbench">
    <div className="crumb"><button onClick={back}>← 项目</button><span>/</span><b>{displayName}</b></div>
    <section className="run-header">
      <div><div className="run-title"><span className="project-icon">{displayName.slice(0, 2).toUpperCase()}</span><h1>{displayName}</h1><Status value={detail?.status || project?.status || 'loading'} /></div>
      <p>{detail?.original_goal || project?.requirement || '正在读取需求…'}</p></div>
      <div className="run-actions"><button onClick={refresh}>刷新</button><button className="danger" disabled={!!busy} onClick={() => action('stop', () => api.stop(projectRef))}>安全停止</button></div>
    </section>
    <nav className="tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</nav>
    {error && <div className="notice error">{error}</div>}
    <div className="workspace-body">
      {tab === 'overview' && <Overview detail={detail} activeStage={activeStage} logs={logs} candidates={candidates} />}
      {tab === 'requirement' && <Document title="原始需求" content={detail?.original_goal || project?.requirement || '暂无需求'} />}
      {tab === 'plan' && <Plan detail={detail} candidates={candidates} />}
      {tab === 'execution' && <Execution detail={detail} events={displayEvents} />}
      {tab === 'verification' && <Verification detail={detail} latest={latestQuality} />}
      {tab === 'changes' && <Changes name={projectRef} candidates={candidates} action={action} busy={busy} />}
      {tab === 'knowledge' && <Knowledge notes={notes} action={action} name={projectRef} busy={busy} />}
      {tab === 'settings' && <Settings project={project} detail={detail} projectRef={projectRef} removed={back} />}
    </div>
  </div>;
}

function Overview({ detail, activeStage, logs, candidates }: { detail: RunDetail | null; activeStage: string; logs: LogEntry[]; candidates: Candidate[] }) {
  const stages = detail?.stages || ['understand', 'plan', 'implement', 'test', 'review', 'stop'];
  const index = Math.max(0, stages.indexOf(activeStage));
  return <div className="overview-grid">
    <section className="panel span-2"><div className="section-heading"><div><p className="eyebrow">NOW</p><h2>当前正在做什么</h2></div><Status value={detail?.status || 'pending'} /></div>
      <div className="now-card"><span className="pulse" /><div><b>{activeStage}</b><p>{humanStage(activeStage)}</p></div><strong>第 {detail?.iteration || 0} 轮</strong></div>
      <div className="stage-track">{stages.map((stage, i) => <div key={stage} className={i < index ? 'done' : i === index ? 'active' : ''}><i>{i < index ? '✓' : i + 1}</i><span>{stage}</span></div>)}</div>
    </section>
    <Metric label="累计成本" value={`$${(detail?.spent || 0).toFixed(3)}`} hint="模型调用估算" />
    <Metric label="改进候选" value={String(candidates.length)} hint="可审核的代码变更" />
    <Metric label="质量快照" value={String(detail?.quality_history.length || 0)} hint="测试与评审证据" />
    <Metric label="事件" value={String(logs.length)} hint="可追溯执行记录" />
    <section className="panel span-2"><p className="eyebrow">EVIDENCE</p><h2>最近证据</h2>
      <EventList events={logs.slice(-6).reverse()} empty="运行开始后，测试、工具与决策证据会出现在这里。" />
    </section>
  </div>;
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <div className="metric panel"><span>{label}</span><b>{value}</b><small>{hint}</small></div>;
}

function Document({ title, content }: { title: string; content: string }) {
  return <section className="document panel"><p className="eyebrow">GOAL VERSION 1</p><h2>{title}</h2><div className="document-content">{content}</div></section>;
}

function Plan({ detail, candidates }: { detail: RunDetail | null; candidates: Candidate[] }) {
  const items = detail?.work_items || [];
  return <div className="split"><section className="panel"><p className="eyebrow">WORK ITEMS</p><h2>实现计划</h2>
    {items.length ? items.map((item, i) => <JsonCard key={i} value={item} />) : <Empty>尚未形成工作项。规划完成后会自动更新。</Empty>}</section>
    <section className="panel"><p className="eyebrow">DECISIONS</p><h2>候选改进</h2>
    {candidates.length ? candidates.map((item, i) => <div className="compact-item" key={item.id || i}><b>{item.title || item.id}</b><span>{item.status || item.impact || 'pending'}</span></div>) : <Empty>暂无待处理候选。</Empty>}</section></div>;
}

function Execution({ detail, events }: { detail: RunDetail | null; events: LogEntry[] }) {
  return <div className="execution-grid"><section className="panel"><p className="eyebrow">STEP</p><h2>阶段时间线</h2>
    {(detail?.stage_history || []).length ? detail!.stage_history.map((event, i) => <JsonCard key={i} value={event} />) : <Empty>暂无阶段事件。</Empty>}</section>
    <section className="panel debug"><p className="eyebrow">DEBUG</p><h2>结构化执行日志</h2><EventList events={events} empty="暂无执行日志。" /></section></div>;
}

function Verification({ detail, latest }: { detail: RunDetail | null; latest: Record<string, unknown> }) {
  return <section className="panel"><div className="section-heading"><div><p className="eyebrow">VERIFICATION</p><h2>质量与交付证据</h2></div><span>{detail?.quality_history.length || 0} 个快照</span></div>
    {detail?.quality_history.length ? <><div className="quality-summary"><Metric label="当前阶段" value={detail.stage} hint="最近一次记录" /><JsonCard value={latest} /></div>
    <div className="history">{detail.quality_history.map((snapshot, i) => <JsonCard key={i} value={snapshot} />)}</div></> : <Empty>测试运行后，这里会展示命令、结果、失败原因与 Reviewer 结论。</Empty>}</section>;
}

function Changes({ name, candidates, action, busy }: { name: string; candidates: Candidate[]; action: (label: string, work: () => Promise<unknown>) => void; busy: string }) {
  return <section className="panel"><p className="eyebrow">CHANGES</p><h2>变更审核</h2>{candidates.length ? <div className="candidate-grid">{candidates.map(candidate => <article className="candidate" key={candidate.id}>
    <div><Status value={candidate.status || 'proposed'} /><span className="score">{candidate.score ?? '—'}</span></div><h3>{candidate.title || candidate.id}</h3>
    <p>{candidate.summary || candidate.description || '暂无说明'}</p><details><summary>查看完整数据</summary><pre>{JSON.stringify(candidate, null, 2)}</pre></details>
    <footer><button disabled={!!busy} onClick={() => action(`approve-${candidate.id}`, () => api.decide(name, candidate.id, 'approve'))}>批准</button>
    <button className="danger" disabled={!!busy} onClick={() => action(`reject-${candidate.id}`, () => api.decide(name, candidate.id, 'reject'))}>拒绝</button></footer>
  </article>)}</div> : <Empty>还没有需要人工审核的变更。</Empty>}</section>;
}

function Knowledge({ notes, action, name, busy }: { notes: Array<Record<string, unknown>>; action: (label: string, work: () => Promise<unknown>) => void; name: string; busy: string }) {
  return <section className="panel"><div className="section-heading"><div><p className="eyebrow">KNOWLEDGE</p><h2>项目知识库</h2></div><button className="primary" disabled={!!busy} onClick={() => action('article', () => api.article(name))}>生成复盘文章</button></div>
    {notes.length ? <div className="note-grid">{notes.map((note, i) => <JsonCard key={i} value={note} />)}</div> : <Empty>完成阶段后会沉淀决策、失败模式与可复用知识。</Empty>}</section>;
}

function Settings({ project, detail, projectRef, removed }: { project: Project | null; detail: RunDetail | null; projectRef: string; removed: () => void }) {
  const [error, setError] = useState('');
  async function download(format: 'md' | 'json') {
    try {
      const { data } = await api.exportAnalysis(projectRef, format);
      const url = URL.createObjectURL(new Blob([data.content], { type: data.media_type }));
      const link = document.createElement('a'); link.href = url; link.download = data.filename; link.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError((e as Error).message); }
  }
  async function remove() {
    if (!window.confirm('删除此项目记录？工作目录和源代码会保留。')) return;
    try { await api.removeProject(projectRef); removed(); } catch (e) { setError((e as Error).message); }
  }
  return <div className="split"><section className="panel"><p className="eyebrow">PROJECT</p><h2>项目设置</h2><dl><dt>工作目录</dt><dd>{project?.workspace_path || '—'}</dd><dt>模式</dt><dd>{project?.mode || '—'}</dd><dt>项目 ID</dt><dd>{project?.id || '—'}</dd></dl>
    <div className="settings-actions"><button onClick={() => download('md')}>导出分析</button><button className="danger" onClick={remove}>删除项目记录</button></div>{error && <div className="notice error">{error}</div>}</section>
  <section className="panel"><p className="eyebrow">RUN OPTIONS</p><h2>执行配置</h2><pre>{JSON.stringify(detail?.options || {}, null, 2)}</pre></section></div>;
}

function EventList({ events, empty }: { events: LogEntry[]; empty: string }) {
  if (!events.length) return <Empty>{empty}</Empty>;
  return <div className="event-list">{events.map((event, i) => <div className="event" key={`${event.offset}-${i}`}><i /><div><b>{event.type || 'event'}</b><span>{summary(event.payload || event)}</span></div><time>{event.timestamp ? shortTime(event.timestamp) : `#${event.offset}`}</time></div>)}</div>;
}

function JsonCard({ value }: { value: Record<string, unknown> }) {
  const title = String(value.title || value.name || value.type || value.stage || '记录');
  return <details className="json-card"><summary>{title}<span>查看</span></summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

function humanStage(stage: string) {
  const labels: Record<string, string> = { understand: '澄清目标并建立需求上下文', plan: '拆分验收项与纵向切片', implement: '批量实现当前切片', test: '运行聚焦质量门禁', review: '检查逻辑与回归风险', stop: '整理交付物并结束' };
  return labels[stage] || '正在推进当前工程任务';
}
function summary(value: unknown) { const text = typeof value === 'string' ? value : JSON.stringify(value); return text.length > 180 ? `${text.slice(0, 177)}…` : text; }
function shortTime(value: string) { try { return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); } catch { return value; } }

export default function App() {
  const [current, setCurrent] = useState<Route>(route());
  useEffect(() => { const change = () => setCurrent(route()); addEventListener('hashchange', change); return () => removeEventListener('hashchange', change); }, []);
  return <div className="app-shell"><header className="topbar"><button className="brand" onClick={() => go({ page: 'projects' })}><span>1P</span><div><b>OnePTeam</b><small>Software development, orchestrated</small></div></button><div className="system-state"><i />本地服务已连接</div></header>
    <main>{current.page === 'workbench' && current.project ? <Workbench name={current.project} back={() => go({ page: 'projects' })} /> : <ProjectList open={name => go({ page: 'workbench', project: name })} />}</main>
    <footer className="app-footer"><span>OnePTeam V2</span><span>Local-first · Durable execution · Verifiable delivery</span></footer></div>;
}
