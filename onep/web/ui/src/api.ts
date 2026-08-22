export type Project = {
  id: string;
  name: string;
  mode: string;
  status: string;
  current_stage: string;
  workspace_path: string;
  requirement: string;
  created_at: string;
  updated_at: string;
  harness?: RunSummary | null;
};

export type RunSummary = {
  id: string;
  status: string;
  stage: string;
  iteration: number;
  spent: number;
  goal: string;
  stop_reason: string;
};

export type Candidate = {
  id: string;
  title?: string;
  summary?: string;
  description?: string;
  score?: number;
  status?: string;
  impact?: string;
  decision?: { note?: string; applied?: boolean };
  [key: string]: unknown;
};

export type RunDetail = {
  id: string;
  project_name: string;
  original_goal: string;
  status: string;
  stage: string;
  iteration: number;
  spent: number;
  started_at: string;
  ended_at: string;
  options: Record<string, unknown>;
  stop_state: Record<string, unknown>;
  quality_history: Array<Record<string, unknown>>;
  improvement_candidates: Candidate[];
  work_items: Array<Record<string, unknown>>;
  knowledge_events: Array<Record<string, unknown>>;
  research_reports: Array<Record<string, unknown>>;
  stages: string[];
  stage_history: Array<Record<string, unknown>>;
  mutations_supported: boolean;
};

export type LogEntry = {
  offset: number;
  type?: string;
  timestamp?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
};

export type Job = {
  id: string;
  capability_id: string;
  project_id: string;
  run_id: string;
  status: string;
  attempts: number;
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Activity = {
  sequence: number;
  project_id: string;
  run_id: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Health = {
  status: "ready" | "degraded";
  api: string;
  database: string;
  worker: { ready: boolean; worker_id: string; last_seen: string };
};

export type ProjectSettings = {
  project_id: string;
  defaults: Record<string, unknown>;
  effective: Record<string, unknown>;
  active_run: Record<string, unknown> | null;
  is_running: boolean;
  revision: string;
  applies_to: string;
};

export type GlobalSettings = {
  settings: {
    llm: Record<string, unknown>;
    pipeline: Record<string, unknown>;
    run_defaults: Record<string, unknown>;
  };
  revision: string;
  applies_to: string;
};

function emptyRunDetail(mutationsSupported: boolean): RunDetail {
  return {
    id: "",
    project_name: "",
    original_goal: "",
    status: "",
    stage: "",
    iteration: 0,
    spent: 0,
    started_at: "",
    ended_at: "",
    options: {},
    stop_state: {},
    quality_history: [],
    improvement_candidates: [],
    work_items: [],
    knowledge_events: [],
    research_reports: [],
    stages: [
      "understand",
      "research",
      "design",
      "plan",
      "build",
      "verify",
      "review",
      "stop",
    ],
    stage_history: [],
    mutations_supported: mutationsSupported,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      body.detail || body.title || `请求失败（${response.status}）`;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  projects: () => request<{ projects: Project[] }>("/api/v1/projects"),
  jobs: (limit = 50) => request<{ jobs: Job[] }>(`/api/v1/jobs?limit=${limit}`),
  activities: (after = 0, projectId = "") =>
    request<{ events: Activity[] }>(
      `/api/v1/events?after=${after}&limit=500${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`,
    ),
  detail: (project: string) =>
    request<{
      run: Omit<RunDetail, "mutations_supported"> | null;
      mutations_supported: boolean;
    }>(`/api/v1/projects/${encodeURIComponent(project)}`).then((value) =>
      value.run
        ? { ...value.run, mutations_supported: value.mutations_supported }
        : emptyRunDetail(value.mutations_supported),
    ),
  logs: (project: string, offset = 0) =>
    request<{ entries: LogEntry[]; next_offset: number }>(
      `/api/v1/projects/${encodeURIComponent(project)}/log?offset=${offset}&limit=500`,
    ),
  create: (payload: Record<string, unknown>, actionId = crypto.randomUUID()) =>
    request<{ project: Project; run_id: string; job_id: string }>(
      "/api/v1/projects",
      {
        method: "POST",
        headers: { "X-Action-ID": actionId },
        body: JSON.stringify(payload),
      },
    ),
  startWorkflow: (capability: string, payload: Record<string, unknown>) =>
    request<{ job_id: string; status: string }>(
      `/api/v1/actions/${capability}`,
      {
        method: "POST",
        headers: { "X-Action-ID": crypto.randomUUID() },
        body: JSON.stringify(payload),
      },
    ),
  stop: (project: string) =>
    request("/api/v1/actions/run.stop", {
      method: "POST",
      body: JSON.stringify({ project_id: project }),
    }),
  cancelJob: (job: string) =>
    request<Job>(`/api/v1/jobs/${encodeURIComponent(job)}/cancel`, {
      method: "POST",
      body: "{}",
    }),
  candidates: (project: string) =>
    request<{ candidates: Candidate[] }>(
      `/api/v1/projects/${encodeURIComponent(project)}/candidates`,
    ),
  decide: (
    project: string,
    id: string,
    decision: "approve" | "reject",
    note = "",
  ) =>
    request(
      `/api/v1/projects/${encodeURIComponent(project)}/candidates/${encodeURIComponent(id)}/${decision}`,
      {
        method: "POST",
        body: JSON.stringify({ note }),
      },
    ),
  article: (project: string) =>
    request<Record<string, string>>(
      `/api/v1/projects/${encodeURIComponent(project)}/article`,
      {
        method: "POST",
        headers: { "X-Action-ID": crypto.randomUUID() },
      },
    ),
  notes: (project: string) =>
    request<{ notes: Array<Record<string, unknown>> }>(
      `/api/v1/projects/${encodeURIComponent(project)}/knowledge`,
    ),
  exportAnalysis: (project: string, format: "md" | "json" = "md") =>
    request<{
      data: { filename: string; content: string; media_type: string };
    }>("/api/v1/actions/analysis.export", {
      method: "POST",
      body: JSON.stringify({ project_id: project, format }),
    }),
  removeProject: (project: string) =>
    request("/api/v1/actions/project.delete", {
      method: "POST",
      body: JSON.stringify({ project_id: project, delete_files: false }),
    }),
  globalSettings: () => request<GlobalSettings>("/api/v1/settings"),
  updateGlobalSettings: (revision: string, patch: Record<string, unknown>) =>
    request<GlobalSettings>("/api/v1/settings", {
      method: "PATCH",
      body: JSON.stringify({ revision, patch }),
    }),
  projectSettings: (project: string) =>
    request<ProjectSettings>(
      `/api/v1/projects/${encodeURIComponent(project)}/settings`,
    ),
  updateProjectSettings: (
    project: string,
    revision: string,
    patch: Record<string, unknown>,
  ) =>
    request<ProjectSettings>(
      `/api/v1/projects/${encodeURIComponent(project)}/settings`,
      {
        method: "PATCH",
        body: JSON.stringify({ revision, patch }),
      },
    ),
  discoverTests: (project: string) =>
    request<{ commands: string[]; executed: boolean }>(
      `/api/v1/projects/${encodeURIComponent(project)}/settings/test-commands/discover`,
      { method: "POST", body: "{}" },
    ),
  testModel: (project: string, kind: "default" | "complex") =>
    request<{ job_id: string }>("/api/v1/actions/settings.model.test", {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: JSON.stringify({ project_id: project, kind }),
    }),
};
