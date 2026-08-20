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
};

export type Candidate = {
  id: string;
  title?: string;
  summary?: string;
  description?: string;
  score?: number;
  status?: string;
  impact?: string;
  [key: string]: unknown;
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
  status: string;
  attempts: number;
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  created_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || body.title || `Request failed (${response.status})`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body as T;
}

export const api = {
  projects: () => request<{ projects: Project[] }>('/api/v1/projects'),
  jobs: () => request<{ jobs: Job[] }>('/api/v1/jobs?limit=12'),
  detail: (name: string) =>
    request<{ run: RunDetail | null }>(`/api/v1/projects/${encodeURIComponent(name)}`).then(value => {
      if (!value.run) throw new Error('run not found');
      return value.run;
    }),
  logs: (name: string, offset = 0) =>
    request<{ entries: LogEntry[]; next_offset: number }>(
      `/api/v1/projects/${encodeURIComponent(name)}/log?offset=${offset}&limit=500`,
    ),
  create: (payload: Record<string, unknown>, actionId: string) =>
    request<{ project: Project; run_id: string; job_id: string }>('/api/v1/projects', {
      method: 'POST',
      headers: { 'X-Action-ID': actionId },
      body: JSON.stringify(payload),
    }),
  startWorkflow: (capability: string, payload: Record<string, unknown>, actionId: string) =>
    request<{ job_id: string; status: string }>(`/api/v1/actions/${capability}`, {
      method: 'POST',
      headers: { 'X-Action-ID': actionId },
      body: JSON.stringify(payload),
    }),
  stop: (name: string) =>
    request('/api/v1/actions/run.stop', {
      method: 'POST', body: JSON.stringify({ project_id: name }),
    }),
  candidates: (name: string) =>
    request<{ candidates: Candidate[] }>(`/api/v1/projects/${encodeURIComponent(name)}/candidates`),
  decide: (name: string, id: string, decision: 'approve' | 'reject') =>
    request(`/api/v1/projects/${encodeURIComponent(name)}/candidates/${encodeURIComponent(id)}/${decision}`, {
      method: 'POST', body: '{}',
    }),
  article: (name: string) =>
    request<Record<string, string>>(`/api/v1/projects/${encodeURIComponent(name)}/article`, {
      method: 'POST', headers: { 'X-Action-ID': crypto.randomUUID() },
    }),
  notes: (name: string) =>
    request<{ notes: Array<Record<string, unknown>> }>(
      `/api/v1/projects/${encodeURIComponent(name)}/knowledge`,
    ),
  exportAnalysis: (name: string, format: 'md' | 'json' = 'md') =>
    request<{ data: { filename: string; content: string; media_type: string } }>(
      '/api/v1/actions/analysis.export', {
        method: 'POST', body: JSON.stringify({ project_id: name, format }),
      },
    ),
  removeProject: (name: string) =>
    request('/api/v1/actions/project.delete', {
      method: 'POST', body: JSON.stringify({ project_id: name, delete_files: false }),
    }),
};
