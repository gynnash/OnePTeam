import { useMemo, useState } from "react";
import { Ban, CircleAlert, ListFilter } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Activity, api, Job } from "../api";
import {
  Badge,
  Button,
  Card,
  Empty,
  JsonInspector,
  LoadFailure,
  Modal,
  PageTitle,
  SectionTitle,
  Skeleton,
} from "../components/ui";
import { isReadActivity, keys, useActivities, useJobs } from "../queries";
import { shortTime, summarize } from "../lib/utils";

const capabilityLabel: Record<string, string> = {
  "project.create": "创建项目",
  "run.start": "开始项目运行",
  "run.resume": "继续项目运行",
  "run.stop": "请求安全停止",
  "candidate.decide": "记录候选决策",
  "article.generate": "生成复盘文章",
  "project.delete": "移除项目记录",
  "analysis.start": "分析代码",
  "optimization.start": "自动优化代码",
  "settings.global.update": "更新全局设置",
  "project.settings.update": "更新项目设置",
  "settings.model.test": "测试模型连接",
};

function describeActivity(event: Activity) {
  const payload = event.payload || {};
  const capability =
    capabilityLabel[String(payload.capability_id || "")] ||
    String(payload.capability_id || "操作");
  if (event.type === "action.requested")
    return { title: `已请求 · ${capability}`, detail: "等待系统确认并执行" };
  if (event.type === "action.completed")
    return {
      title: `已完成 · ${capability}`,
      detail: summarize(payload.result || "操作已完成"),
    };
  if (event.type === "action.failed")
    return {
      title: `操作失败 · ${capability}`,
      detail: summarize(payload.problem || payload.error || "请检查诊断"),
    };
  if (event.type.startsWith("job."))
    return {
      title: `后台任务 · ${event.type.slice(4)}`,
      detail: String(
        payload.capability_id
          ? capability
          : payload.status || payload.job_id || "任务状态已更新",
      ),
    };
  if (event.type.startsWith("run."))
    return {
      title: `项目运行 · ${event.type.slice(4)}`,
      detail: String(payload.project || payload.detail || "运行状态已更新"),
    };
  if (event.type === "workflow.output")
    return {
      title: "执行输出",
      detail: String(payload.line || "已产生新的运行证据"),
    };
  return { title: event.type, detail: summarize(payload) };
}

export function TasksPage() {
  const jobs = useJobs();
  const activities = useActivities();
  const client = useQueryClient();
  const [filter, setFilter] = useState("all");
  const [cancelTarget, setCancelTarget] = useState<Job | null>(null);
  const cancel = useMutation({
    mutationFn: api.cancelJob,
    onSuccess: () => {
      toast.success("已提交取消请求");
      setCancelTarget(null);
      client.invalidateQueries({ queryKey: keys.jobs });
    },
    onError: (error) => toast.error(error.message),
  });
  const items = useMemo(
    () =>
      (jobs.data?.jobs || []).filter(
        (job) => filter === "all" || job.status === filter,
      ),
    [filter, jobs.data],
  );
  const visibleActivities = (activities.data?.events || []).filter(
    (event) => !isReadActivity(event),
  );
  return (
    <div className="page">
      <PageTitle
        eyebrow="ACTIVITY"
        title="任务与活动"
        detail="查看队列、运行结果和跨项目操作。完整工程证据保留在项目工作台。"
      />
      <div className="toolbar">
        <div className="filter-row">
          <ListFilter size={15} />
          {["all", "running", "queued", "failed", "succeeded", "cancelled"].map(
            (value) => (
              <button
                key={value}
                className={filter === value ? "active" : ""}
                onClick={() => setFilter(value)}
              >
                {value === "all" ? "全部" : <Badge value={value} />}
              </button>
            ),
          )}
        </div>
      </div>
      <div className="tasks-layout">
        <Card>
          <SectionTitle
            eyebrow="JOBS"
            title="后台任务"
            meta={`${items.length} 项`}
          />
          {jobs.isLoading ? (
            <Skeleton className="h-64" />
          ) : jobs.isError ? (
            <LoadFailure
              title="无法读取任务队列"
              onRetry={() => jobs.refetch()}
            />
          ) : items.length ? (
            <div className="job-table">
              {items.map((job) => (
                <div className="job-row" key={job.id}>
                  <Badge value={job.status} />
                  <div>
                    <b>{job.capability_id}</b>
                    <span>
                      {job.id.slice(0, 8)} · 尝试 {job.attempts} 次
                    </span>
                  </div>
                  <time>{shortTime(job.updated_at)}</time>
                  {(job.status === "queued" ||
                    (job.status === "running" &&
                      [
                        "run.start",
                        "run.resume",
                        "analysis.start",
                        "optimization.start",
                      ].includes(job.capability_id))) && (
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={cancel.isPending}
                      onClick={() =>
                        job.status === "queued"
                          ? cancel.mutate(job.id)
                          : setCancelTarget(job)
                      }
                    >
                      <Ban size={14} />
                      {job.status === "queued"
                        ? "取消排队"
                        : ["run.start", "run.resume"].includes(
                              job.capability_id,
                            )
                          ? "安全停止"
                          : "立即取消"}
                    </Button>
                  )}
                  <JsonInspector
                    value={
                      job.error && Object.keys(job.error).length
                        ? job.error
                        : job.result
                    }
                    label="诊断"
                  />
                </div>
              ))}
            </div>
          ) : (
            <Empty icon={<CircleAlert />} title="没有匹配的任务" />
          )}
        </Card>
        <Card>
          <SectionTitle
            eyebrow="EVENTS"
            title="最近活动"
            meta={`${visibleActivities.length} 条`}
          />
          {activities.isLoading ? (
            <Skeleton className="h-64" />
          ) : activities.isError ? (
            <LoadFailure
              title="无法读取活动记录"
              onRetry={() => activities.refetch()}
            />
          ) : visibleActivities.length ? (
            <div className="record-list compact">
              {visibleActivities
                .slice(-30)
                .reverse()
                .map((event) => {
                  const description = describeActivity(event);
                  return (
                    <div className="activity-row" key={event.sequence}>
                      <i />
                      <div>
                        <b>{description.title}</b>
                        <p>{description.detail}</p>
                        <JsonInspector value={event.payload} label="原始事件" />
                      </div>
                      <time>{shortTime(event.created_at)}</time>
                    </div>
                  );
                })}
            </div>
          ) : (
            <Empty
              icon={<CircleAlert />}
              title="还没有需要展示的活动"
              detail="项目运行、设置修改与后台任务会出现在这里。"
            />
          )}
        </Card>
      </div>
      <Modal
        open={!!cancelTarget}
        onOpenChange={(open) => !open && setCancelTarget(null)}
        title={
          cancelTarget &&
          ["run.start", "run.resume"].includes(cancelTarget.capability_id)
            ? "安全停止项目运行？"
            : "立即取消外部流程？"
        }
        detail={
          cancelTarget &&
          ["run.start", "run.resume"].includes(cancelTarget.capability_id)
            ? "系统会在下一个安全迭代边界停止，并保留已产生的代码与证据。"
            : "分析或优化子进程会被终止，已经写入的运行记录仍会保留。"
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setCancelTarget(null)}>
              继续运行
            </Button>
            <Button
              variant="danger"
              disabled={cancel.isPending}
              onClick={() => cancelTarget && cancel.mutate(cancelTarget.id)}
            >
              确认停止
            </Button>
          </>
        }
      >
        <div className="form-note">
          <CircleAlert size={16} />
          停止后可从任务诊断与项目证据中查看最终状态。
        </div>
      </Modal>
    </div>
  );
}
