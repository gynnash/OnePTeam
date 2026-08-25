import type { Project } from "../api";

export type ProjectGroup = {
  key: string;
  name: string;
  projects: Project[];
  latest: Project;
};

export function normalizeProjectName(value: string) {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
}

function updatedAt(project: Project) {
  const timestamp = new Date(project.updated_at).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function groupProjects(projects: Project[]): ProjectGroup[] {
  const grouped = new Map<string, Project[]>();

  projects.forEach((project) => {
    const key = normalizeProjectName(project.name) || "未命名项目";
    grouped.set(key, [...(grouped.get(key) || []), project]);
  });

  return Array.from(grouped, ([key, values]) => {
    const sorted = [...values].sort(
      (left, right) => updatedAt(right) - updatedAt(left),
    );
    const latest = sorted[0];
    return {
      key,
      name: latest.name.trim() || "未命名项目",
      projects: sorted,
      latest,
    };
  }).sort((left, right) => updatedAt(right.latest) - updatedAt(left.latest));
}
