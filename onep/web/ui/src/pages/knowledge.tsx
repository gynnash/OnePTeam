import { BookOpen, Network } from "lucide-react";
import { Link } from "react-router";
import {
  Card,
  Empty,
  LoadFailure,
  PageTitle,
  SectionTitle,
} from "../components/ui";
import { useProjects } from "../queries";

export function KnowledgePage() {
  const projects = useProjects();
  const withKnowledge = (projects.data?.projects || []).filter(
    (project) => project.harness,
  );
  return (
    <div className="page">
      <PageTitle
        eyebrow="KNOWLEDGE"
        title="知识"
        detail="从运行中的决策、失败和验证证据形成可迁移的工程知识。"
      />
      <div className="knowledge-hero">
        <Card>
          <Network size={22} />
          <h2>项目知识图谱</h2>
          <p>
            知识与原始运行证据保持关联；进入项目可以查看笔记并生成复盘文章。
          </p>
        </Card>
        <Card>
          <BookOpen size={22} />
          <h2>可解释的复盘</h2>
          <p>文章以验收、决策和实验为主线，而不是简单拼接终端日志。</p>
        </Card>
      </div>
      <Card>
        <SectionTitle eyebrow="PROJECT VAULTS" title="项目知识库" />
        {projects.isError ? (
          <LoadFailure onRetry={() => projects.refetch()} />
        ) : withKnowledge.length ? (
          <div className="project-stack">
            {withKnowledge.map((project) => (
              <Link key={project.id} to={`/projects/${project.id}/delivery`}>
                <span className="project-glyph">
                  {project.name.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <b>{project.name}</b>
                  <p>{project.requirement || "查看项目知识与交付物"}</p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <Empty
            icon={<BookOpen />}
            title="还没有可展示的知识"
            detail="项目运行后，决策和证据会沉淀到这里。"
          />
        )}
      </Card>
    </div>
  );
}
