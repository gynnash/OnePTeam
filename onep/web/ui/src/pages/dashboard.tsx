import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FolderKanban,
  PlayCircle,
  Plus,
} from "lucide-react";
import { Link } from "react-router";
import { useJobs, useProjects } from "../queries";
import { useUIStore } from "../store";
import { stageLabel, shortTime } from "../lib/utils";
import {
  Badge,
  Button,
  Card,
  Empty,
  LoadFailure,
  PageTitle,
  RecordRow,
  SectionTitle,
  Skeleton,
} from "../components/ui";

export function DashboardPage() {
  const projects = useProjects();
  const jobs = useJobs();
  const setComposer = useUIStore((state) => state.setComposerOpen);
  const allProjects = projects.data?.projects || [];
  const allJobs = jobs.data?.jobs || [];
  const active = allJobs.filter((job) =>
    ["queued", "running", "cancel_requested"].includes(job.status),
  );
  const failures = allJobs.filter((job) => job.status === "failed").slice(0, 4);
  const completed = allProjects.filter((project) =>
    ["completed", "succeeded"].includes(
      project.harness?.status || project.status,
    ),
  ).length;

  return (
    <div className="page dashboard">
      <PageTitle
        eyebrow="COMMAND CENTER"
        title="今天需要关注什么？"
        detail="监控 Agent 运行、处理异常，并从一个清晰目标开始下一项工作。"
        actions={
          <Button variant="primary" onClick={() => setComposer(true)}>
            <Plus size={16} />
            新建任务
          </Button>
        }
      />
      <section className="metric-grid">
        <Card className="metric-card">
          <span>正在运行</span>
          <b>{jobs.isError ? "—" : active.length}</b>
          <small>
            <PlayCircle size={13} />
            含排队与安全停止
          </small>
        </Card>
        <Card className="metric-card">
          <span>需要处理</span>
          <b>{jobs.isError ? "—" : failures.length}</b>
          <small>
            <CircleAlert size={13} />
            最近失败任务
          </small>
        </Card>
        <Card className="metric-card">
          <span>项目</span>
          <b>{projects.isError ? "—" : allProjects.length}</b>
          <small>
            <FolderKanban size={13} />
            {completed} 个已完成
          </small>
        </Card>
        <Card className="metric-card accent">
          <span>交付原则</span>
          <b>Evidence</b>
          <small>
            <CheckCircle2 size={13} />
            只相信可验证结果
          </small>
        </Card>
      </section>

      {failures.length > 0 && (
        <Card className="attention-card">
          <SectionTitle
            eyebrow="ACTION REQUIRED"
            title="需要处理"
            meta={`${failures.length} 项`}
          />
          <div className="record-list">
            {failures.map((job) => (
              <RecordRow
                key={job.id}
                status={job.status}
                title={job.capability_id}
                detail={
                  job.error?.detail ||
                  job.error?.title ||
                  "任务执行失败，请检查诊断。"
                }
                meta={
                  <Link to="/tasks">
                    查看诊断 <ArrowRight size={13} />
                  </Link>
                }
              />
            ))}
          </div>
        </Card>
      )}

      <div className="dashboard-grid">
        <Card>
          <SectionTitle
            eyebrow="NOW"
            title="正在运行"
            meta={<Link to="/tasks">全部任务</Link>}
          />
          {jobs.isLoading ? (
            <Skeleton className="h-40" />
          ) : jobs.isError ? (
            <LoadFailure
              title="无法读取运行队列"
              onRetry={() => jobs.refetch()}
            />
          ) : active.length ? (
            <div className="record-list">
              {active.slice(0, 6).map((job) => (
                <RecordRow
                  key={job.id}
                  status={job.status}
                  title={job.capability_id}
                  detail={
                    job.status === "cancel_requested"
                      ? "正在到达安全停止边界"
                      : `任务 ${job.id.slice(0, 8)}`
                  }
                  meta={<time>{shortTime(job.updated_at)}</time>}
                />
              ))}
            </div>
          ) : (
            <Empty
              icon={<Clock3 />}
              title="当前没有运行中的任务"
              detail="队列空闲，可以开始下一项工作。"
              action={
                <Button onClick={() => setComposer(true)}>创建任务</Button>
              }
            />
          )}
        </Card>
        <Card>
          <SectionTitle
            eyebrow="RECENT"
            title="最近项目"
            meta={<Link to="/projects">全部项目</Link>}
          />
          {projects.isLoading ? (
            <Skeleton className="h-40" />
          ) : projects.isError ? (
            <LoadFailure
              title="无法读取项目"
              onRetry={() => projects.refetch()}
            />
          ) : allProjects.length ? (
            <div className="project-stack">
              {allProjects.slice(0, 5).map((project) => {
                const run = project.harness;
                const status = run?.status || project.status;
                return (
                  <Link key={project.id} to={`/projects/${project.id}/goal`}>
                    <span className="project-glyph">
                      {project.name.slice(0, 2).toUpperCase()}
                    </span>
                    <div>
                      <b>{project.name}</b>
                      <p>
                        {project.requirement || run?.goal || "暂无目标说明"}
                      </p>
                    </div>
                    <aside>
                      <Badge value={status} />
                      <small>
                        {stageLabel[run?.stage || project.current_stage] ||
                          "尚未开始"}
                      </small>
                    </aside>
                  </Link>
                );
              })}
            </div>
          ) : (
            <Empty
              icon={<Bot />}
              title="还没有项目"
              detail="三步开始：选择工作流、定义目标、查看可验证结果。"
              action={
                <Button variant="primary" onClick={() => setComposer(true)}>
                  <Plus size={16} />
                  创建第一个任务
                </Button>
              }
            />
          )}
        </Card>
      </div>
    </div>
  );
}
