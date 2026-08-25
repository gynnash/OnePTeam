import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Activity, BookOpen, CheckCircle2, ChevronRight, CircleAlert, FileCheck2,
  GitBranch, Layers3, MessageSquareText, Pause, Play, ShieldCheck, Square,
} from "lucide-react";
import { Link, NavLink, Navigate, useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import {
  DiscoveryQuestion, DiscoverySnapshot, PrdValidation, ProductAssumption,
  StudioFeature, studioApi,
} from "../api";
import { Badge, Button, Card, Empty, JsonInspector, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";
import { studioKeys, useStudioProject } from "../queries";
import { canApprovePrd } from "../lib/prd-review";
import { discoveryDimensionLabel, shortTime, summarize } from "../lib/utils";

const sections = [
  ["vision", "Vision"], ["conversation", "Conversation"], ["prd", "PRD"],
  ["features", "Feature Map"], ["release", "Release"], ["build", "Build"],
  ["verification", "Verification"], ["knowledge", "Knowledge"], ["delivery", "Delivery"],
] as const;

function Definition({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value || {});
  return entries.length ? (
    <div className="definition-grid">
      {entries.map(([key, item]) => <article key={key}><span>{key.replaceAll("_", " ")}</span><p>{summarize(item, 600)}</p></article>)}
    </div>
  ) : <Empty title="产品定义尚未形成" detail="回答需求发现问题后，系统会生成完整产品定位。" />;
}

function Conversation({ projectId, discovery }: { projectId: string; discovery: DiscoverySnapshot }) {
  const client = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const pending = discovery.pending_questions;
  const assessment = discovery.assessment;
  const answer = useMutation({
    mutationFn: () => studioApi.answer(projectId, pending.map((question) => ({ question_id: question.id, answer: answers[question.id] || "" }))),
    onSuccess: async () => {
      toast.success("回答已保存，产品完整度已重新评估");
      setAnswers({});
      await client.invalidateQueries({ queryKey: studioKeys.project(projectId) });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "提交失败"),
  });
  const decision = useMutation({
    mutationFn: (action: "continue" | "accept_recommendations" | "draft_with_assumptions") => studioApi.discoveryDecision(projectId, action),
    onSuccess: async (_, action) => {
      toast.success(action === "draft_with_assumptions" ? "已生成带假设的 PRD 草稿" : "Discovery 已继续");
      await client.invalidateQueries({ queryKey: studioKeys.project(projectId) });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "操作失败"),
  });
  if (!discovery.questions.length && discovery.session?.status !== "checkpoint") return <Empty title="没有待澄清问题" detail="系统正在评估产品定义，或已经进入 PRD Review。" />;
  return (
    <div className="discovery-workspace">
      {assessment && <section className="discovery-assessment">
        <header><div><b>产品定义完整度</b><span>第 {Math.max(1, assessment.round_number)} 轮评估</span></div><strong>{Math.round(assessment.readiness_score * 100)}%</strong></header>
        <div className="coverage-grid">{Object.entries(assessment.coverage).map(([dimension, status]) => <div key={dimension}><span>{discoveryDimensionLabel[dimension] || dimension.replaceAll("_", " ")}</span><Badge value={status} /></div>)}</div>
        {assessment.policy_blockers.length > 0 && <details><summary>为什么还不能生成可审批 PRD</summary><ul>{assessment.policy_blockers.map((item) => <li key={item}>{item}</li>)}</ul></details>}
        {assessment.conflicts.length > 0 && <div className="validation-blockers"><b>信息冲突</b>{assessment.conflicts.map((item) => <p key={item}>{item}</p>)}</div>}
      </section>}
      <form className="conversation-stack" onSubmit={(event) => { event.preventDefault(); answer.mutate(); }}>
      {discovery.questions.map((question, index) => (
        <article key={question.id} className={question.status === "answered" ? "answered" : ""}>
          <header><span>R{question.round_number} · {String(index + 1).padStart(2, "0")}</span><Badge value={question.status} /></header>
          <h3>{question.question}</h3><p>{question.impact}</p>
          {question.recommended_answer && <aside><b>系统建议</b><p>{question.recommended_answer}</p><small>{question.recommendation_reason}</small></aside>}
          {question.status === "pending" ? question.options.length && ["single_choice", "confirm"].includes(question.question_type) ? <select required value={answers[question.id] || ""} onChange={(event) => setAnswers((value) => ({ ...value, [question.id]: event.target.value }))}><option value="">请选择…</option>{question.options.map((option) => <option key={option}>{option}</option>)}</select> : <textarea required={question.required} value={answers[question.id] || ""} onChange={(event) => setAnswers((value) => ({ ...value, [question.id]: event.target.value }))} placeholder={question.question_type === "multi_choice" ? "可填写多个选择及原因…" : "给出会影响产品方向的答案…"} /> : <blockquote>{question.answer}</blockquote>}
        </article>
      ))}
      {pending.length > 0 && <Button variant="primary" type="submit" disabled={answer.isPending || pending.some((question) => question.required && !(answers[question.id] || "").trim())}>{answer.isPending ? "正在重新评估…" : "提交回答并评估"}</Button>}
      </form>
      {discovery.session?.status === "checkpoint" && <section className="discovery-checkpoint"><CircleAlert /><div><h3>需要你决定下一步</h3><p>系统仍发现重要缺口。可以继续澄清，采用全部可用建议，或先生成带明确假设的 PRD 草稿。</p><div><Button onClick={() => decision.mutate("continue")} disabled={decision.isPending}>继续澄清</Button><Button onClick={() => decision.mutate("accept_recommendations")} disabled={decision.isPending || !assessment?.next_questions.some((item) => Boolean(item.recommended_answer))}>采用系统建议</Button><Button variant="primary" onClick={() => decision.mutate("draft_with_assumptions")} disabled={decision.isPending}>生成带假设草稿</Button></div></div></section>}
    </div>
  );
}

function FeatureCard({ feature, releaseSelected, onToggle, strategy, onStrategy }: { feature: StudioFeature; releaseSelected: boolean; onToggle?: () => void; strategy?: string; onStrategy?: (value: string) => void }) {
  return (
    <article className="feature-card">
      <header><div><span>{feature.id}</span><h3>{feature.title}</h3></div>{onToggle && <label className="release-check"><input type="checkbox" checked={releaseSelected} onChange={onToggle} />当前 Release</label>}</header>
      <p>{feature.product_role}</p><strong>用户收益</strong><p>{feature.user_outcome}</p>
      <footer>{onStrategy ? <label>Codex 模式 <select disabled={!releaseSelected} value={strategy || feature.execution_strategy} onChange={(event) => onStrategy(event.target.value)}><option value="direct">Direct</option><option value="plan_then_execute">Plan → Execute</option><option value="goal">Goal</option><option value="plan_then_goal">Plan → Goal</option></select></label> : <Badge value={feature.execution_strategy} />}<span>{feature.strategy_reason}</span></footer>
      <details><summary>范围与验收</summary><ul>{feature.acceptance.map((item) => <li key={item}>{item}</li>)}</ul><JsonInspector value={feature} label="完整 FeatureSpec" /></details>
    </article>
  );
}

function PrdReview({ projectId, projectState, prd, validation, assumptions }: { projectId: string; projectState: string; prd: NonNullable<ReturnType<typeof useStudioProject>["data"]>["prd"]; validation: PrdValidation | null; assumptions: ProductAssumption[] }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [feedback, setFeedback] = useState("");
  const features = prd?.document.features || [];
  const [selected, setSelected] = useState<string[]>(prd?.document.release_feature_ids || []);
  const [strategies, setStrategies] = useState<Record<string, string>>(() => Object.fromEntries(features.map((feature) => [feature.id, feature.execution_strategy])));
  useEffect(() => {
    setSelected(prd?.document.release_feature_ids || []);
    setStrategies(Object.fromEntries((prd?.document.features || []).map((feature) => [feature.id, feature.execution_strategy])));
  }, [prd?.version]);
  const approve = useMutation({
    mutationFn: () => studioApi.approvePrd(projectId, prd!.version, selected, Object.fromEntries(selected.map((featureId) => [featureId, strategies[featureId]]))),
    onSuccess: async () => {
      toast.success("PRD 与 Release 已批准，Codex 执行已进入队列");
      await client.invalidateQueries({ queryKey: studioKeys.project(projectId) });
      navigate(`/projects/${projectId}/build`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "批准失败"),
  });
  const resolveAssumption = useMutation({
    mutationFn: ({ assumption, status }: { assumption: ProductAssumption; status: "accepted" | "rejected" }) => studioApi.resolvePrdAssumption(projectId, prd!.version, assumption.id, assumption.revision, status, status === "accepted" ? "用户确认此假设可作为当前产品决定" : "用户拒绝此假设，需要修订 PRD"),
    onSuccess: async () => client.invalidateQueries({ queryKey: studioKeys.project(projectId) }),
    onError: (error) => toast.error(error instanceof Error ? error.message : "假设处理失败"),
  });
  const revise = useMutation({
    mutationFn: () => studioApi.feedbackPrd(projectId, prd!.version, feedback),
    onSuccess: async () => {
      toast.success("已根据反馈生成新的不可变 PRD 版本");
      setFeedback("");
      await client.invalidateQueries({ queryKey: studioKeys.project(projectId) });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "PRD 修订失败"),
  });
  const revalidate = useMutation({
    mutationFn: () => studioApi.revalidatePrd(projectId, prd!.version),
    onSuccess: async () => client.invalidateQueries({ queryKey: studioKeys.project(projectId) }),
    onError: (error) => toast.error(error instanceof Error ? error.message : "验证失败"),
  });
  if (!prd) return <Empty title="PRD 尚未生成" detail="先完成 Conversation 中的需求澄清。" />;
  const canApprove = canApprovePrd(validation, assumptions);
  return <div className="prd-document">
    <header><div><Badge value={prd.status} /><span>v{prd.version}</span></div><h2>{prd.document.summary}</h2><p>{prd.document.positioning}</p></header>
    <section className={`prd-validation ${validation?.passed ? "passed" : "blocked"}`}><SectionTitle title="PRD 独立验证" meta={validation?.passed ? "可以进入人工审批" : `${validation?.blockers.length || 0} 个 blocker`} />{validation ? <><div className="validation-summary"><Badge value={validation.passed ? "passed" : "blocked"} /><span>检查定位、范围、冲突、风险、假设、验收可测性和 Release 闭环</span></div>{validation.blockers.length > 0 && <div className="validation-blockers">{validation.blockers.map((item) => <p key={item}>{item}</p>)}</div>}{validation.warnings.length > 0 && <details><summary>{validation.warnings.length} 个 warning</summary><ul>{validation.warnings.map((item) => <li key={item}>{item}</li>)}</ul></details>}<Button size="sm" onClick={() => revalidate.mutate()} disabled={revalidate.isPending}>{revalidate.isPending ? "正在验证…" : "重新验证"}</Button></> : <Empty title="尚未验证 PRD" />}</section>
    {assumptions.length > 0 && <section className="prd-assumptions"><SectionTitle title="产品假设" meta={`${assumptions.filter((item) => item.status === "pending").length} 个待确认`} /><div>{assumptions.map((assumption) => <article key={assumption.id}><header><Badge value={assumption.status} /><Badge value={assumption.risk} /></header><h3>{assumption.statement}</h3><p>{assumption.impact}</p><small>来源：{assumption.source}</small>{assumption.status === "pending" && <footer><Button size="sm" onClick={() => resolveAssumption.mutate({ assumption, status: "accepted" })}>接受为当前决定</Button><Button size="sm" variant="danger" onClick={() => resolveAssumption.mutate({ assumption, status: "rejected" })}>拒绝并修订</Button></footer>}</article>)}</div></section>}
    <div className="prd-facts"><Definition value={prd.document.project_definition} /><article><h3>Requirements</h3>{prd.document.requirements.map((requirement, index) => <p key={String(requirement.id || index)}><b>{String(requirement.id || `REQ-${index + 1}`)}</b>{summarize(requirement, 500)}</p>)}</article><article><h3>风险</h3><ul>{prd.document.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul></article></div>
    <SectionTitle title="本次 Release" meta={`${selected.length}/${features.length} 个功能`} />
    <div className="feature-grid">{features.map((feature) => <FeatureCard key={feature.id} feature={feature} releaseSelected={selected.includes(feature.id)} onToggle={prd.status === "approved" ? undefined : () => setSelected((value) => value.includes(feature.id) ? value.filter((id) => id !== feature.id) : [...value, feature.id])} strategy={strategies[feature.id]} onStrategy={prd.status === "approved" ? undefined : (value) => setStrategies((current) => ({ ...current, [feature.id]: value }))} />)}</div>
    {prd.status !== "approved" && <section className="prd-feedback"><SectionTitle title="纠正或补充 PRD" meta="每次修订都会创建新版本" /><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="指出错误假设、遗漏功能、范围冲突或不可测验收标准…" /><Button disabled={revise.isPending || !feedback.trim()} onClick={() => revise.mutate()}>{revise.isPending ? "正在修订…" : "根据反馈生成新版本"}</Button></section>}
    {prd.status !== "approved" && <div className="approval-bar"><div><ShieldCheck /><span><b>批准后才会修改代码</b><small>{canApprove ? "批准的是这个不可变 PRD 版本和选中的 Release 范围。" : "先解决 Validation blocker 和高风险假设。"}</small></span></div><Button variant="primary" disabled={approve.isPending || !selected.length || projectState !== "prd_review" || !canApprove} onClick={() => approve.mutate()}>{approve.isPending ? "正在批准…" : "批准 PRD 并开始交付"}</Button></div>}
  </div>;
}

function Build({ projectId, units }: { projectId: string; units: NonNullable<ReturnType<typeof useStudioProject>["data"]>["execution_units"] }) {
  const client = useQueryClient();
  const strategy = useMutation({
    mutationFn: ({ feature, mode }: { feature: string; mode: string }) => studioApi.setStrategy(projectId, feature, mode, "用户在 Build 页面覆盖自动选择"),
    onSuccess: () => client.invalidateQueries({ queryKey: studioKeys.project(projectId) }),
    onError: (error) => toast.error(error instanceof Error ? error.message : "策略更新失败"),
  });
  return units.length ? <div className="execution-list">{units.map((unit, index) => <article key={unit.id}>
    <header><span>{String(index + 1).padStart(2, "0")}</span><div><h3>{unit.title}</h3><p>{unit.objective}</p></div><Badge value={unit.status} /></header>
    <div className="unit-meta"><label>Codex 模式<select disabled={unit.status !== "pending"} value={unit.strategy} onChange={(event) => strategy.mutate({ feature: unit.feature_id, mode: event.target.value })}><option value="direct">Direct</option><option value="plan_then_execute">Plan → Execute</option><option value="goal">Goal</option><option value="plan_then_goal">Plan → Goal</option></select></label><span>{unit.strategy_reason}</span></div>
    {unit.plan.length > 0 && <ol>{unit.plan.map((step) => <li key={step.step}><Badge value={step.status} />{step.step}</li>)}</ol>}
    <JsonInspector value={unit} label="ExecutionUnit 与 Codex 线程" />
  </article>)}</div> : <Empty title="还没有执行单元" detail="批准 PRD 与 Release 后，Plan 会被编译为与 Feature 对齐的执行 DAG。" />;
}

function Knowledge({ projectId, records, applications }: { projectId: string; records: NonNullable<ReturnType<typeof useStudioProject>["data"]>["knowledge"]; applications: Array<Record<string, unknown>> }) {
  return <><div className="knowledge-workspace"><Card><SectionTitle title="项目知识账本" meta={`${records.length} 条`} />{records.length ? <div className="record-list">{records.map((record) => <div className="record-row" key={record.id}><Badge value={record.validity} /><div><b>{record.title}</b><p>{record.summary}</p><small>{record.type} · 可信度 {Math.round(record.confidence * 100)}%</small></div></div>)}</div> : <Empty title="尚无工程知识" detail="批准、失败、修复、Review 与验证结果会在关键边界自动沉淀。" />}</Card><Card><SectionTitle title="历史知识应用" meta={`${applications.length} 次`} />{applications.length ? <JsonInspector value={applications} label="查看来源与复用结果" /> : <Empty title="尚未应用历史知识" detail="相关知识会在规划、修复和 Goal 停滞时作为带来源先验注入。" />}</Card></div><Link className="article-cta" to={`/articles?project=${encodeURIComponent(projectId)}`}><div><BookOpen /><span><b>基于这个项目生成技术文章</b><small>也可在下一步加入相关项目与历史复用记录</small></span></div><ChevronRight /></Link></>;
}

function PendingInteractions({ projectId, interactions }: { projectId: string; interactions: Array<Record<string, unknown>> }) {
  const client = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const pending = interactions.filter((item) => item.status === "pending");
  const resolve = useMutation({
    mutationFn: ({ id, revision, response }: { id: string; revision: number; response: string }) => studioApi.resolveInteraction(id, revision, response),
    onSuccess: () => client.invalidateQueries({ queryKey: studioKeys.project(projectId) }),
    onError: (error) => toast.error(error instanceof Error ? error.message : "响应失败"),
  });
  if (!pending.length) return null;
  const optionLabel = (option: string, index: number) => {
    if (option.includes('"permissions"')) return option.includes('"permissions": {}') ? "拒绝" : "仅本次允许";
    if (option === "acceptForSession") return "本次会话允许";
    if (option === "accept") return "允许";
    if (["decline", "cancel"].includes(option)) return "拒绝";
    return `选项 ${index + 1}`;
  };
  return <Card className="interaction-panel"><SectionTitle title="Codex 正在等待你" meta={`${pending.length} 个阻塞请求`} /><div>{pending.map((item) => { const options = item.options as string[] || []; const id = String(item.id); return <article key={id}><div><Badge value={String(item.kind)} /><p>{String(item.prompt)}</p></div>{options.length ? <div>{options.map((option, index) => <Button size="sm" key={option} variant={option.includes("accept") || (option.includes('"permissions"') && !option.includes('"permissions": {}')) ? "primary" : "secondary"} onClick={() => resolve.mutate({ id, revision: Number(item.revision), response: option })}>{optionLabel(option, index)}</Button>)}</div> : <div className="interaction-answer"><textarea value={answers[id] || ""} onChange={(event) => setAnswers((value) => ({ ...value, [id]: event.target.value }))} placeholder="输入你的回答；多个问题可逐行回答" /><Button variant="primary" size="sm" disabled={!(answers[id] || "").trim()} onClick={() => resolve.mutate({ id, revision: Number(item.revision), response: answers[id] })}>提交回答</Button></div>}</article>; })}</div></Card>;
}

export function StudioProjectPage() {
  const { projectId = "", section = "vision" } = useParams();
  const query = useStudioProject(projectId);
  const client = useQueryClient();
  const action = useMutation({ mutationFn: (value: "pause" | "resume" | "stop") => studioApi.projectAction(projectId, value), onSuccess: () => client.invalidateQueries({ queryKey: studioKeys.project(projectId) }), onError: (error) => toast.error(error instanceof Error ? error.message : "操作失败") });
  if (!sections.some(([id]) => id === section)) return <Navigate to={`/projects/${projectId}/vision`} replace />;
  if (query.isLoading) return <div className="page"><Skeleton className="h-64" /></div>;
  if (query.isError || !query.data) return <div className="page"><LoadFailure onRetry={() => query.refetch()} /></div>;
  const data = query.data;
  const project = data.project;
  const featureMap = data.prd?.document.features || [];
  let content: ReactNode;
  if (section === "vision") content = <><Card><SectionTitle title="产品定义" /><Definition value={project.definition} /></Card><Card><SectionTitle title="Current Product Baseline" /><Definition value={project.baseline} /></Card></>;
  else if (section === "conversation") content = <Card><SectionTitle title="需求发现" meta="每轮最多 3 个问题，以信息充分度决定是否继续" /><Conversation projectId={projectId} discovery={data.discovery} /></Card>;
  else if (section === "prd") content = <Card><PrdReview projectId={projectId} projectState={project.state} prd={data.prd} validation={data.prd_validation} assumptions={data.assumptions} /></Card>;
  else if (section === "features") content = <Card><SectionTitle title="Feature Map" meta={`${featureMap.length} 个功能`} />{featureMap.length ? <div className="feature-grid">{featureMap.map((feature) => <FeatureCard key={feature.id} feature={feature} releaseSelected={data.release?.feature_ids.includes(feature.id) || false} />)}</div> : <Empty title="等待 PRD" />}</Card>;
  else if (section === "release") content = <Card><SectionTitle title="当前 Release" meta={data.release ? `PRD v${data.release.prd_version}` : "未批准"} />{data.release ? <><div className="release-summary"><CheckCircle2 /><div><h3>{data.release.feature_ids.length} 个 Feature 已获批准</h3><p>任何产品范围变化都会创建新 PRD 版本并重新审批。</p></div></div><JsonInspector value={data.release} label="ReleaseScope" /></> : <Empty title="尚未批准 Release" detail="在 PRD 页确认首发范围。" />}</Card>;
  else if (section === "build") content = <Card><SectionTitle title="Codex 执行" meta="每个 Feature 一个持久根线程" /><Build projectId={projectId} units={data.execution_units} /></Card>;
  else if (section === "verification") content = <Card><SectionTitle title="独立质量门" meta={`${data.evidence.length} 条证据`} />{data.evidence.length ? <div className="record-list">{data.evidence.map((item, index) => <div className="record-row" key={String(item.id || index)}><Badge value={String(item.status || "pending")} /><div><b>{String(item.kind || item.type || "验证证据")}</b><p>{summarize(item, 300)}</p></div><JsonInspector value={item} label="证据详情" /></div>)}</div> : <Empty icon={<FileCheck2 />} title="尚无验证证据" detail="Codex 完成后由 OnePTeam 独立计算 diff、测试、指纹并启动 Detached Review。" />}</Card>;
  else if (section === "knowledge") content = <Knowledge projectId={projectId} records={data.knowledge} applications={data.knowledge_applications} />;
  else content = <Card><SectionTitle title="Delivery" meta={<Badge value={project.state} />} />{project.state === "delivered" ? <div className="delivery-ready"><CheckCircle2 /><h2>已通过全部验收门</h2><p>Release、Feature、Requirement、执行单元、代码指纹和验证证据均可追溯。</p></div> : <Empty icon={<CircleAlert />} title="尚未满足交付条件" detail="Goal 完成不等于验收通过；测试和独立 Review 都必须通过。" />}</Card>;
  return <div className="page project-studio-page">
    <PageTitle eyebrow={`Product Studio · ${project.state}`} title={project.name} detail={project.idea} actions={!["discovery", "prd_review", "delivered", "stopped"].includes(project.state) ? <><Button size="sm" onClick={() => action.mutate(project.state === "paused" ? "resume" : "pause")}>{project.state === "paused" ? <Play size={14} /> : <Pause size={14} />}{project.state === "paused" ? "继续" : "暂停"}</Button><Button size="sm" variant="danger" onClick={() => action.mutate("stop")}><Square size={13} />停止</Button></> : undefined} />
    <div className="studio-state-strip"><span className="active"><MessageSquareText />产品定义</span><ChevronRight /><span className={data.release ? "active" : ""}><Layers3 />Release</span><ChevronRight /><span className={data.execution_units.some((unit) => unit.status !== "pending") ? "active" : ""}><GitBranch />Codex</span><ChevronRight /><span className={data.evidence.length ? "active" : ""}><Activity />验证与知识</span></div>
    <nav className="product-tabs">{sections.map(([id, label]) => <NavLink key={id} to={`/projects/${projectId}/${id}`}>{label}</NavLink>)}</nav>
    <PendingInteractions projectId={projectId} interactions={data.interactions} />
    <div className="studio-section">{content}</div>
  </div>;
}
