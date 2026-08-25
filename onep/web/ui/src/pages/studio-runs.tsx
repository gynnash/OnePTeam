import { Activity, XCircle } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { studioApi } from "../api";
import { Badge, Button, Card, Empty, JsonInspector, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";
import { studioKeys, useStudioJobs } from "../queries";

export function StudioRunsPage() {
  const jobs = useStudioJobs();
  const client = useQueryClient();
  const cancel = useMutation({
    mutationFn: studioApi.cancelJob,
    onSuccess: () => client.invalidateQueries({ queryKey: studioKeys.jobs }),
  });
  return (
    <div className="page tasks-page">
      <PageTitle eyebrow="Codex Runtime" title="运行" detail="查看获批 Release 的 Codex 执行、验证、知识提炼和阻塞状态。" />
      <Card>
        <SectionTitle title="执行队列" meta={`${jobs.data?.jobs.length || 0} 项`} />
        {jobs.isLoading ? <Skeleton className="h-64" /> : jobs.isError ? (
          <LoadFailure onRetry={() => jobs.refetch()} />
        ) : jobs.data?.jobs.length ? (
          <div className="activity-stream">
            {jobs.data.jobs.map((job) => (
              <article className="activity-item activity-job" key={job.id}>
                <div className="activity-marker"><Activity size={15} /></div>
                <div className="activity-copy">
                  <header><Badge value={job.status} /><time>{new Date(job.updated_at).toLocaleString()}</time></header>
                  <h2>{job.capability_id}</h2><p>项目 {job.project_id} · 第 {job.attempts} 次执行</p>
                  <JsonInspector value={job.error && Object.keys(job.error).length ? job.error : job.result} label="运行详情" />
                </div>
                {["queued", "running"].includes(job.status) && (
                  <Button variant="danger" size="sm" onClick={() => cancel.mutate(job.id)}><XCircle size={14} />停止</Button>
                )}
              </article>
            ))}
          </div>
        ) : <Empty icon={<Activity />} title="暂无执行" detail="批准 PRD 和当前 Release 后，执行会自动进入这里。" />}
      </Card>
    </div>
  );
}

