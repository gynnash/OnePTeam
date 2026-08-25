import { ArrowRight, BookOpen, FileText, Sparkles } from "lucide-react";
import { Link } from "react-router";
import { useStudioProjects, useStudioKnowledge, useArticles } from "../queries";
import { useUIStore } from "../store";
import { Badge, Button, Card, Empty, LoadFailure, PageTitle, SectionTitle, Skeleton } from "../components/ui";

const phases = ["一句话", "交互澄清", "完整 PRD", "Codex 实现", "独立验证", "知识复用"];

export function StudioDashboardPage() {
  const projects = useStudioProjects();
  const knowledge = useStudioKnowledge("");
  const articles = useArticles();
  const openComposer = useUIStore((state) => state.openComposer);

  return (
    <div className="page dashboard-page">
      <PageTitle
        eyebrow="Product Studio"
        title="把模糊想法变成清晰产品，再让 Codex 可靠交付"
        detail="OnePTeam 负责产品定位、需求验证、执行编排和知识复用；Codex 专注工程实现。"
        actions={<Button variant="primary" onClick={() => openComposer()}><Sparkles size={16} />定义新产品</Button>}
      />
      <Card className="studio-value-chain">
        <SectionTitle title="完整闭环" meta="批准 PRD 前零代码写入" />
        <div className="stage-track">
          {phases.map((phase, index) => (
            <div key={phase} className="stage-node completed">
              <span>{index + 1}</span><b>{phase}</b>
            </div>
          ))}
        </div>
      </Card>
      <section className="metric-grid">
        <Card><Sparkles size={18} /><strong>{projects.data?.projects.length || 0}</strong><span>产品项目</span></Card>
        <Card><BookOpen size={18} /><strong>{knowledge.data?.records.length || 0}</strong><span>结构化知识</span></Card>
        <Card><FileText size={18} /><strong>{articles.data?.articles.length || 0}</strong><span>技术文章</span></Card>
      </section>
      <Card>
        <SectionTitle title="最近项目" action={<Link to="/projects">查看全部 <ArrowRight size={14} /></Link>} />
        {projects.isLoading ? <Skeleton className="h-64" /> : projects.isError ? (
          <LoadFailure onRetry={() => projects.refetch()} />
        ) : projects.data?.projects.length ? (
          <div className="knowledge-list">
            {projects.data.projects.slice(0, 6).map((project) => (
              <Link key={project.id} to={`/projects/${project.id}/vision`}>
                <span className="knowledge-index">{project.name.slice(0, 2)}</span>
                <div><header><h2>{project.name}</h2><Badge value={project.state} /></header><p>{project.idea}</p></div>
                <ArrowRight size={17} />
              </Link>
            ))}
          </div>
        ) : (
          <Empty title="还没有产品项目" detail="用一句话描述想做的产品，OnePTeam 会从需求发现开始。" action={<Button onClick={() => openComposer()}>开始定义</Button>} />
        )}
      </Card>
    </div>
  );
}

