import { ArrowRight, FolderKanban, Plus } from "lucide-react";
import { Link } from "react-router";
import { Badge, Button, Card, Empty, LoadFailure, PageTitle, Skeleton } from "../components/ui";
import { useStudioProjects } from "../queries";
import { useUIStore } from "../store";

export function StudioProjectsPage() {
  const projects = useStudioProjects();
  const openComposer = useUIStore((state) => state.openComposer);
  return (
    <div className="page projects-page">
      <PageTitle
        eyebrow="产品组合"
        title="项目"
        detail="每个项目都有独立的产品定位、PRD 版本、Release、执行证据和知识资产。"
        actions={<Button variant="primary" onClick={() => openComposer()}><Plus size={16} />新产品</Button>}
      />
      {projects.isLoading ? <Skeleton className="h-64" /> : projects.isError ? (
        <LoadFailure onRetry={() => projects.refetch()} />
      ) : projects.data?.projects.length ? (
        <div className="project-grid">
          {projects.data.projects.map((project) => (
            <Link className="project-card" key={project.id} to={`/projects/${project.id}/vision`}>
              <header><span className="project-monogram">{project.name.slice(0, 2)}</span><Badge value={project.state} /></header>
              <h2>{project.name}</h2><p>{project.idea}</p>
              <footer><span>{project.workspace_path}</span><ArrowRight size={16} /></footer>
            </Link>
          ))}
        </div>
      ) : (
        <Card><Empty icon={<FolderKanban />} title="还没有项目" detail="新项目和现有代码库都从同一个产品发现入口开始。" /></Card>
      )}
    </div>
  );
}

