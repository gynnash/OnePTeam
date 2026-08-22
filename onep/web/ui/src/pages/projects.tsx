import { useMemo, useState } from "react";
import { Grid2X2, List, Plus, Search } from "lucide-react";
import { Link } from "react-router";
import {
  Badge,
  Button,
  Card,
  Empty,
  LoadFailure,
  PageTitle,
  Skeleton,
} from "../components/ui";
import { useProjects } from "../queries";
import { useUIStore } from "../store";
import { stageLabel, shortTime } from "../lib/utils";

export function ProjectsPage() {
  const projects = useProjects();
  const setComposer = useUIStore((state) => state.setComposerOpen);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const items = useMemo(
    () =>
      (projects.data?.projects || []).filter((project) =>
        `${project.name} ${project.requirement}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [projects.data, query],
  );
  return (
    <div className="page">
      <PageTitle
        eyebrow="WORKSPACES"
        title="项目"
        detail="每个项目保存目标、运行证据、交付物与可恢复状态。"
        actions={
          <Button variant="primary" onClick={() => setComposer(true)}>
            <Plus size={16} />
            新建任务
          </Button>
        }
      />
      <div className="toolbar">
        <label className="search-field">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目或目标"
          />
        </label>
        <div className="segmented">
          <button
            className={view === "grid" ? "active" : ""}
            onClick={() => setView("grid")}
          >
            <Grid2X2 size={15} />
          </button>
          <button
            className={view === "list" ? "active" : ""}
            onClick={() => setView("list")}
          >
            <List size={15} />
          </button>
        </div>
      </div>
      {projects.isLoading ? (
        <div className="project-grid">
          {[1, 2, 3].map((value) => (
            <Skeleton key={value} className="h-56" />
          ))}
        </div>
      ) : projects.isError ? (
        <Card>
          <LoadFailure onRetry={() => projects.refetch()} />
        </Card>
      ) : items.length ? (
        <div className={view === "grid" ? "project-grid" : "project-list"}>
          {items.map((project) => {
            const run = project.harness;
            const status = run?.status || project.status;
            return (
              <Link
                className="project-card"
                key={project.id}
                to={`/projects/${project.id}/goal`}
              >
                <div className="project-card-top">
                  <span className="project-glyph">
                    {project.name.slice(0, 2).toUpperCase()}
                  </span>
                  <Badge value={status} />
                </div>
                <h2>{project.name}</h2>
                <p>{project.requirement || run?.goal || "暂无目标说明"}</p>
                <footer>
                  <span>
                    {stageLabel[run?.stage || project.current_stage] ||
                      "尚未开始"}
                  </span>
                  <time>{shortTime(project.updated_at)}</time>
                </footer>
              </Link>
            );
          })}
        </div>
      ) : (
        <Card>
          <Empty
            icon={<Search />}
            title="没有匹配的项目"
            detail="调整搜索条件，或创建一项新任务。"
          />
        </Card>
      )}
    </div>
  );
}
