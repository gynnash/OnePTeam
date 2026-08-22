import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  GitPullRequest,
  PanelRightClose,
  PanelRightOpen,
  ScrollText,
  Settings,
  Square,
  Target,
} from "lucide-react";
import { Link, NavLink, Navigate, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, Candidate, LogEntry } from "../api";
import {
  Badge,
  Button,
  Card,
  Empty,
  JsonInspector,
  LoadFailure,
  Modal,
  PageTitle,
  RecordRow,
  SectionTitle,
  Skeleton,
} from "../components/ui";
import { ProjectSettingsPanel } from "../components/project-settings";
import { keys, useProjectData, useProjects } from "../queries";
import { useUIStore } from "../store";
import { stageLabel, shortTime, summarize } from "../lib/utils";

const sections = [
  { id: "goal", label: "目标", icon: Target },
  { id: "plan", label: "计划", icon: ScrollText },
  { id: "run", label: "执行", icon: GitPullRequest },
  { id: "verification", label: "验证", icon: FileCheck2 },
  { id: "delivery", label: "交付", icon: CheckCircle2 },
];

export function ProjectPage() {
  const { projectId = "", section = "goal" } = useParams();
  const projects = useProjects();
  const data = useProjectData(projectId);
  const client = useQueryClient();
  const navigate = useNavigate();
  const inspector = useUIStore((state) => state.inspectorOpen);
  const setInspector = useUIStore((state) => state.setInspectorOpen);
  const project = projects.data?.projects.find(
    (item) => item.id === projectId || item.name === projectId,
  );
  const detail = data.detail.data;
  const candidates = data.candidates.data?.candidates || [];
  const [confirmStop, setConfirmStop] = useState(false);
  const status =
    detail?.status || project?.harness?.status || project?.status || "pending";
  const stop = useMutation({
    mutationFn: () => api.stop(projectId),
    onSuccess: () => {
      toast.success("已请求在下一个安全边界停止");
      client.invalidateQueries({ queryKey: keys.detail(projectId) });
    },
    onError: (error) => toast.error(error.message),
  });
  if (!sections.some((item) => item.id === section) && section !== "settings")
    return <Navigate to={`/projects/${projectId}/goal`} replace />;
  if (projects.isLoading || data.detail.isLoading)
    return (
      <div className="page">
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    );
  if (projects.isError || data.detail.isError)
    return (
      <div className="page">
        <Card>
          <LoadFailure
            title="无法加载项目工作台"
            detail="项目记录仍然存在；这次读取没有返回完整数据。"
            onRetry={() => {
              projects.refetch();
              data.detail.refetch();
            }}
          />
        </Card>
      </div>
    );
  if (!project)
    return (
      <div className="page">
        <Empty
          icon={<CircleAlert />}
          title="找不到项目"
          detail="项目可能已被删除，或链接已失效。"
          action={
            <Button onClick={() => navigate("/projects")}>返回项目</Button>
          }
        />
      </div>
    );
  const completedItems = (detail?.work_items || []).filter(
    (item) => item.status === "completed",
  ).length;
  return (
    <div className="page project-page">
      <Link className="back-link" to="/projects">
        <ArrowLeft size={14} />
        项目
      </Link>
      <PageTitle
        eyebrow={project.mode.toUpperCase()}
        title={project.name}
        detail={detail?.original_goal || project.requirement || "暂无目标说明"}
        actions={
          <>
            <Badge value={status} />
            {["running", "queued"].includes(status) && (
              <Button
                variant="danger"
                disabled={stop.isPending}
                onClick={() => setConfirmStop(true)}
              >
                <Square size={14} />
                安全停止
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              aria-label={inspector ? "收起项目检查器" : "打开项目检查器"}
              onClick={() => setInspector(!inspector)}
            >
              {inspector ? (
                <PanelRightClose size={17} />
              ) : (
                <PanelRightOpen size={17} />
              )}
            </Button>
          </>
        }
      />
      <nav className="lifecycle-nav">
        {sections.map(({ id, label, icon: Icon }) => (
          <NavLink key={id} to={`/projects/${project.id}/${id}`}>
            <Icon size={16} />
            <span>{label}</span>
          </NavLink>
        ))}
        <NavLink
          className="project-settings-link"
          aria-label="项目设置"
          title="项目设置"
          to={`/projects/${project.id}/settings`}
        >
          <Settings size={16} />
        </NavLink>
      </nav>
      <div
        className={
          inspector ? "project-layout" : "project-layout inspector-hidden"
        }
      >
        <div className="project-content">
          {section === "goal" && <GoalView project={project} detail={detail} />}
          {section === "plan" &&
            (data.candidates.isLoading ? (
              <Skeleton className="h-64" />
            ) : data.candidates.isError ? (
              <Card>
                <LoadFailure
                  title="无法读取候选与计划"
                  onRetry={() => data.candidates.refetch()}
                />
              </Card>
            ) : (
              <PlanView
                items={detail?.work_items || []}
                candidates={candidates}
              />
            ))}
          {section === "run" &&
            (data.logs.isLoading ? (
              <Skeleton className="h-64" />
            ) : data.logs.isError ? (
              <Card>
                <LoadFailure
                  title="无法读取执行日志"
                  onRetry={() => data.logs.refetch()}
                />
              </Card>
            ) : (
              <RunView
                history={detail?.stage_history || []}
                logs={data.logs.data?.entries || []}
              />
            ))}
          {section === "verification" && (
            <VerificationView snapshots={detail?.quality_history || []} />
          )}
          {section === "delivery" &&
            (data.candidates.isLoading || data.notes.isLoading ? (
              <Skeleton className="h-64" />
            ) : data.candidates.isError || data.notes.isError ? (
              <Card>
                <LoadFailure
                  title="无法读取交付数据"
                  onRetry={() => {
                    data.candidates.refetch();
                    data.notes.refetch();
                  }}
                />
              </Card>
            ) : (
              <DeliveryView
                projectId={project.id}
                candidates={candidates}
                notes={data.notes.data?.notes || []}
                mutationsSupported={detail?.mutations_supported !== false}
              />
            ))}
          {section === "settings" &&
            (data.settings.isLoading ? (
              <Skeleton className="h-64" />
            ) : data.settings.isError ? (
              <Card>
                <LoadFailure
                  title="无法读取项目设置"
                  onRetry={() => data.settings.refetch()}
                />
              </Card>
            ) : (
              <ProjectSettingsPanel
                project={project}
                settings={data.settings.data}
              />
            ))}
        </div>
        {inspector && (
          <aside className="inspector">
            <div className="inspector-sticky">
              <SectionTitle eyebrow="CONTEXT" title="当前上下文" />
              <dl>
                <dt>状态</dt>
                <dd>
                  <Badge value={status} />
                </dd>
                <dt>当前阶段</dt>
                <dd title={detail?.stage}>
                  {stageLabel[detail?.stage || ""] ||
                    detail?.stage ||
                    "尚未开始"}
                </dd>
                <dt>工程轮次</dt>
                <dd>{detail?.iteration || 0}</dd>
                <dt>累计成本</dt>
                <dd>${Number(detail?.spent || 0).toFixed(3)}</dd>
                <dt>工作项</dt>
                <dd>
                  {completedItems} / {detail?.work_items.length || 0}
                </dd>
              </dl>
              <div className="inspector-evidence">
                <b>最近证据</b>
                {(data.logs.data?.entries || [])
                  .slice(-4)
                  .reverse()
                  .map((event, index) => (
                    <div key={`${event.offset}-${index}`}>
                      <i />
                      <span>{event.type || "event"}</span>
                      <small>
                        {event.timestamp
                          ? shortTime(event.timestamp)
                          : `#${event.offset}`}
                      </small>
                    </div>
                  ))}
              </div>
              {detail && (
                <JsonInspector value={detail} label="检查运行原始数据" />
              )}
            </div>
          </aside>
        )}
      </div>
      <Modal
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title="在安全边界停止运行？"
        detail="系统会完成当前不可中断步骤，然后停止后续迭代。已产生的代码与证据都会保留。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmStop(false)}>
              继续运行
            </Button>
            <Button
              variant="danger"
              disabled={stop.isPending}
              onClick={() =>
                stop.mutate(undefined, {
                  onSuccess: () => setConfirmStop(false),
                })
              }
            >
              确认安全停止
            </Button>
          </>
        }
      >
        <div className="form-note">
          <CircleAlert size={16} />
          停止可能需要等待当前工具或质量命令结束。
        </div>
      </Modal>
    </div>
  );
}

function GoalView({
  project,
  detail,
}: {
  project: { requirement: string };
  detail: ReturnType<typeof useProjectData>["detail"]["data"];
}) {
  const stages = detail?.stages || [
    "understand",
    "research",
    "design",
    "plan",
    "build",
    "verify",
    "review",
    "stop",
  ];
  const current = stages.indexOf(detail?.stage || "");
  return (
    <>
      <Card className="goal-document">
        <span className="eyebrow">GOAL VERSION 1</span>
        <h2>原始目标</h2>
        <p>{detail?.original_goal || project.requirement || "暂无目标说明"}</p>
      </Card>
      <Card>
        <SectionTitle
          eyebrow="LIFECYCLE"
          title="交付路径"
          meta={detail?.id ? `第 ${detail.iteration} 轮` : "尚未开始"}
        />
        <div className="stage-stepper">
          {stages.map((stage, index) => (
            <div
              key={stage}
              className={
                index < current ? "done" : index === current ? "active" : ""
              }
            >
              <i>{index < current ? "✓" : index + 1}</i>
              <span>{stageLabel[stage] || stage}</span>
              <small>{stage}</small>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}

function PlanView({
  items,
  candidates,
}: {
  items: Array<Record<string, unknown>>;
  candidates: Candidate[];
}) {
  return (
    <div className="content-grid">
      <Card>
        <SectionTitle
          eyebrow="WORK ITEMS"
          title="实现计划"
          meta={`${items.length} 项`}
        />
        {items.length ? (
          <div className="work-items">
            {items.map((item, index) => (
              <article key={String(item.id || index)}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <b>{String(item.title || item.id || "工作项")}</b>
                  <p>
                    {String(item.description || item.summary || "等待执行")}
                  </p>
                </div>
                <Badge value={String(item.status || "pending")} />
                <JsonInspector value={item} />
              </article>
            ))}
          </div>
        ) : (
          <Empty
            icon={<ScrollText />}
            title="尚未形成计划"
            detail="完成目标理解后，工作项会自动出现在这里。"
          />
        )}
      </Card>
      <Card>
        <SectionTitle
          eyebrow="DECISIONS"
          title="候选改进"
          meta={`${candidates.length} 项`}
        />
        {candidates.length ? (
          candidates.map((candidate) => (
            <RecordRow
              key={candidate.id}
              status={candidate.status || "pending"}
              title={candidate.title || candidate.id}
              detail={candidate.summary}
            />
          ))
        ) : (
          <Empty icon={<GitPullRequest />} title="没有候选改进" />
        )}
      </Card>
    </div>
  );
}

function RunView({
  history,
  logs,
}: {
  history: Array<Record<string, unknown>>;
  logs: LogEntry[];
}) {
  const [filter, setFilter] = useState("all");
  const [follow, setFollow] = useState(true);
  const tail = useRef<HTMLDivElement>(null);
  const types = [
    "all",
    ...Array.from(new Set(logs.map((item) => item.type || "event"))).slice(
      0,
      5,
    ),
  ];
  const visible = logs
    .filter((item) => filter === "all" || item.type === filter)
    .slice(-160)
    .reverse();
  return (
    <div className="run-grid">
      <Card>
        <SectionTitle
          eyebrow="STEP"
          title="阶段时间线"
          meta={`${history.length} 个节点`}
        />
        {history.length ? (
          <div className="timeline">
            {history.map((event, index) => (
              <div key={index}>
                <i />
                <div>
                  <b>
                    {stageLabel[String(event.stage || event.to || "")] ||
                      String(event.stage || event.type || "阶段事件")}
                  </b>
                  <p>{summarize(event)}</p>
                </div>
                <JsonInspector value={event} />
              </div>
            ))}
          </div>
        ) : (
          <Empty icon={<GitPullRequest />} title="暂无阶段事件" />
        )}
      </Card>
      <Card className="log-console">
        <SectionTitle
          eyebrow="EVIDENCE"
          title="结构化执行日志"
          action={
            <Button size="sm" onClick={() => setFollow(!follow)}>
              {follow ? "暂停跟随" : "自动跟随"}
            </Button>
          }
        />
        <div className="log-filters">
          {types.map((type) => (
            <button
              key={type}
              className={filter === type ? "active" : ""}
              onClick={() => setFilter(type)}
            >
              {type}
            </button>
          ))}
        </div>
        <div className="log-list">
          {visible.length ? (
            visible.map((event, index) => (
              <div key={`${event.offset}-${index}`}>
                <span>
                  {event.timestamp
                    ? shortTime(event.timestamp)
                    : `#${event.offset}`}
                </span>
                <b>{event.type || "event"}</b>
                <p>{summarize(event.payload || event, 260)}</p>
                <JsonInspector value={event} label="原始" />
              </div>
            ))
          ) : (
            <Empty icon={<ScrollText />} title="暂无执行日志" />
          )}
          <div ref={tail} />
        </div>
      </Card>
    </div>
  );
}

function VerificationView({
  snapshots,
}: {
  snapshots: Array<Record<string, unknown>>;
}) {
  return (
    <Card>
      <SectionTitle
        eyebrow="QUALITY"
        title="验证与评审证据"
        meta={`${snapshots.length} 个快照`}
      />
      {snapshots.length ? (
        <div className="quality-grid">
          {snapshots
            .slice()
            .reverse()
            .map((snapshot, index) => {
              const passed =
                snapshot.hard_gates_passed !== false && !snapshot.blockers;
              return (
                <article key={index}>
                  <div
                    className={
                      passed ? "quality-icon passed" : "quality-icon failed"
                    }
                  >
                    {passed ? <CheckCircle2 /> : <CircleAlert />}
                  </div>
                  <div>
                    <b>
                      {String(
                        snapshot.stage ||
                          snapshot.type ||
                          `质量快照 ${snapshots.length - index}`,
                      )}
                    </b>
                    <p>
                      {passed
                        ? "已记录确定性验证证据"
                        : "仍有门禁或阻塞项需要处理"}
                    </p>
                  </div>
                  <JsonInspector value={snapshot} />
                </article>
              );
            })}
        </div>
      ) : (
        <Empty
          icon={<FileCheck2 />}
          title="尚无验证证据"
          detail="测试和评审完成后，命令、结果与风险会显示在这里。"
        />
      )}
    </Card>
  );
}

function DeliveryView({
  projectId,
  candidates,
  notes,
  mutationsSupported,
}: {
  projectId: string;
  candidates: Candidate[];
  notes: Array<Record<string, unknown>>;
  mutationsSupported: boolean;
}) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<{
    candidate: Candidate;
    action: "approve" | "reject";
  } | null>(null);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: () =>
      decision
        ? api.decide(projectId, decision.candidate.id, decision.action, note)
        : Promise.resolve(),
    onSuccess: () => {
      toast.success("候选决策已保存");
      setDecision(null);
      setNote("");
      client.invalidateQueries({ queryKey: keys.candidates(projectId) });
    },
    onError: (error) => toast.error(error.message),
  });
  const article = useMutation({
    mutationFn: () => api.article(projectId),
    onSuccess: () => toast.success("复盘文章已进入生成队列"),
    onError: (error) => toast.error(error.message),
  });
  return (
    <div className="content-grid">
      {!mutationsSupported && (
        <div className="form-note legacy-note">
          <CircleAlert size={16} />
          这是历史项目：运行与证据仍可查看，但候选决策和文章生成已设为只读。
        </div>
      )}
      <Card>
        <SectionTitle
          eyebrow="CHANGES"
          title="变更审核"
          meta={`${candidates.length} 项`}
        />
        {candidates.length ? (
          <div className="candidate-list">
            {candidates.map((candidate) => (
              <article key={candidate.id}>
                <div>
                  <Badge value={candidate.status || "pending"} />
                  <span className="score">{candidate.score ?? "—"}</span>
                </div>
                <h3>{candidate.title || candidate.id}</h3>
                <p>
                  {candidate.summary || candidate.description || "暂无说明"}
                </p>
                <footer>
                  <Button
                    size="sm"
                    disabled={!mutationsSupported}
                    onClick={() =>
                      setDecision({ candidate, action: "approve" })
                    }
                  >
                    批准
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={!mutationsSupported}
                    onClick={() => setDecision({ candidate, action: "reject" })}
                  >
                    拒绝
                  </Button>
                </footer>
                <JsonInspector value={candidate} />
              </article>
            ))}
          </div>
        ) : (
          <Empty icon={<GitPullRequest />} title="没有待审核变更" />
        )}
      </Card>
      <Card>
        <SectionTitle
          eyebrow="KNOWLEDGE"
          title="项目知识与交付物"
          action={
            <Button
              size="sm"
              disabled={!mutationsSupported}
              onClick={() => article.mutate()}
            >
              <BookOpen size={14} />
              生成复盘文章
            </Button>
          }
        />
        {notes.length ? (
          <div className="note-list">
            {notes.map((note, index) => (
              <RecordRow
                key={index}
                title={String(
                  note.title || note.name || note.type || "知识记录",
                )}
                detail={note.summary || note.path || note}
              />
            ))}
          </div>
        ) : (
          <Empty
            icon={<BookOpen />}
            title="还没有知识笔记"
            detail="完成阶段后会沉淀决策、失败模式与可复用知识。"
          />
        )}
      </Card>
      <Modal
        open={!!decision}
        onOpenChange={(open) => {
          if (!open) {
            setDecision(null);
            setNote("");
          }
        }}
        title={decision?.action === "approve" ? "批准候选改进" : "拒绝候选改进"}
        detail={decision?.candidate.title || decision?.candidate.id}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDecision(null)}>
              取消
            </Button>
            <Button
              variant={decision?.action === "reject" ? "danger" : "primary"}
              disabled={decide.isPending || !note.trim()}
              onClick={() => decide.mutate()}
            >
              确认{decision?.action === "approve" ? "批准" : "拒绝"}
            </Button>
          </>
        }
      >
        <label className="field">
          <span>决策理由（必填）</span>
          <textarea
            required
            autoFocus
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="记录风险判断、证据或后续条件"
          />
        </label>
      </Modal>
    </div>
  );
}
