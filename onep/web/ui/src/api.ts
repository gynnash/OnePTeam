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
  workflow_job?: {
    id: string;
    capability_id: string;
    status: string;
  } | null;
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
  runtime: {
    backend_id?: string;
    capabilities?: Record<string, boolean>;
    probe?: Record<string, unknown>;
  };
  delivery_contract: {
    contract_id?: string;
    version?: number;
    status?: string;
    requirement_count?: number;
    work_item_count?: number;
  };
  evidence: {
    candidate?: number;
    verified?: number;
    rejected?: number;
    invalidated?: number;
  };
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
  api?: string;
  database: string;
  worker: { ready: boolean; worker_id: string; last_seen: string };
  runtime?: string;
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
    execution: Record<string, unknown>;
  };
  revision: string;
  applies_to: string;
};

export type RuntimeProbe = {
  backend_id: string;
  available: boolean;
  detail: string;
  authentication: string;
  capabilities: Record<string, boolean>;
  models: string[];
};

export type UnifiedTask = {
  workflow: "build" | "analyze" | "optimize";
  rationale: string;
  repository: {
    source: string;
    kind: string;
    is_git: boolean;
    exists: boolean;
    branch: string;
    current_branch: string;
    code_files: number;
    has_code: boolean;
  };
  project: Project | null;
  run_id: string;
  job_id: string;
};

export type DirectorySelection = {
  path: string;
  branch: string;
  cancelled: boolean;
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
    runtime: {},
    delivery_contract: {},
    evidence: {},
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
  const method = String(init?.method || "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && !headers.has("X-Action-ID")) {
    headers.set("X-Action-ID", crypto.randomUUID());
  }
  const response = await fetch(path, {
    ...init,
    headers,
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
  pickDirectory: (initialPath = "") =>
    request<DirectorySelection>("/api/v1/system/pick-directory", {
      method: "POST",
      body: JSON.stringify({ initial_path: initialPath }),
    }),
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
  startTask: (payload: Record<string, unknown>) =>
    request<UnifiedTask>("/api/v1/tasks", {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
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
  testRuntime: (execution: Record<string, unknown>) =>
    request<RuntimeProbe>("/api/v1/settings/runtime/test", {
      method: "POST",
      body: JSON.stringify({ execution }),
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

export type StudioProject = {
  id: string;
  name: string;
  idea: string;
  workspace_path: string;
  state: string;
  definition: Record<string, unknown>;
  baseline: Record<string, unknown>;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type DiscoveryQuestion = {
  id: string;
  project_id: string;
  round_id: string;
  round_number: number;
  dimension: string;
  question: string;
  impact: string;
  question_type: "free_text" | "single_choice" | "multi_choice" | "confirm";
  options: string[];
  recommended_answer: string;
  recommendation_reason: string;
  required: boolean;
  status: "pending" | "answered";
  answer: string;
  created_at: string;
};

export type DiscoveryAssessment = {
  id: string;
  round_number: number;
  ready_to_draft: boolean;
  readiness_score: number;
  coverage: Record<string, "confirmed" | "assumed" | "missing" | "conflicted" | "not_applicable">;
  confirmed_facts: string[];
  assumptions: Array<Record<string, unknown>>;
  open_decisions: Array<Record<string, unknown>>;
  conflicts: string[];
  risk_flags: string[];
  next_questions: Array<Record<string, unknown>>;
  policy_blockers: string[];
};

export type DiscoverySnapshot = {
  session: null | {
    id: string;
    status: "active" | "checkpoint" | "ready" | "completed";
    current_round: number;
    revision: number;
  };
  rounds: Array<Record<string, unknown> & { questions: DiscoveryQuestion[] }>;
  assessment: DiscoveryAssessment | null;
  assessments: DiscoveryAssessment[];
  questions: DiscoveryQuestion[];
  pending_questions: DiscoveryQuestion[];
};

export type ProductAssumption = {
  id: string;
  project_id: string;
  prd_version: number;
  statement: string;
  source: string;
  impact: string;
  risk: string;
  status: "pending" | "accepted" | "rejected" | "replaced";
  resolution: string;
  revision: number;
};

export type PrdValidation = {
  id: string;
  project_id: string;
  prd_version: number;
  passed: boolean;
  blockers: string[];
  warnings: string[];
  issues: Array<Record<string, unknown>>;
  follow_up_questions: Array<Record<string, unknown>>;
};

export type StudioFeature = {
  id: string;
  title: string;
  product_role: string;
  target_users: string[];
  user_outcome: string;
  scope: string[];
  non_scope: string[];
  flows: string[];
  rules: string[];
  dependencies: string[];
  acceptance: string[];
  metrics: string[];
  verification_commands: string[];
  execution_strategy: string;
  strategy_reason: string;
};

export type PrdVersion = {
  id: string;
  project_id: string;
  version: number;
  status: string;
  document: {
    project_definition: Record<string, unknown>;
    baseline: Record<string, unknown>;
    summary: string;
    positioning: string;
    requirements: Array<Record<string, unknown>>;
    features: StudioFeature[];
    release_feature_ids: string[];
    risks: string[];
    assumptions: Array<Record<string, unknown>>;
    open_questions: string[];
    decision_log: Array<Record<string, unknown>>;
    discovery_assessment_id: string;
    readiness_snapshot: Record<string, unknown>;
    validation_summary: Record<string, unknown>;
  };
  change_summary: string;
  created_at: string;
  approved_at: string;
};

export type ExecutionUnit = {
  id: string;
  project_id: string;
  release_id: string;
  feature_id: string;
  title: string;
  objective: string;
  acceptance: string[];
  verification_commands: string[];
  dependencies: string[];
  strategy: string;
  strategy_reason: string;
  status: string;
  thread_id: string;
  plan: Array<{ step: string; status: string }>;
  attempt: number;
};

export type KnowledgeRecord = {
  id: string;
  project_id: string;
  type: string;
  title: string;
  summary: string;
  validity: string;
  confidence: number;
  generalizable: boolean;
  technology_stack: string[];
  components: string[];
  tags: string[];
  root_cause?: string;
  final_fix?: string;
  revision: number;
  updated_at: string;
};

export type ArticleModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
  api_base: string;
  parameters: Record<string, unknown>;
  credential_configured: boolean;
  credential_mask: string;
  credential_source: "os_keyring" | "missing";
  is_default: boolean;
  active: boolean;
  revision: number;
};

export type Article = {
  id: string;
  title: string;
  status: string;
  current_version: number;
  brief: Record<string, unknown>;
  source_pack_id: string;
  model_profile_id: string;
  selected_version: number;
  versions: Array<{ version: number; long_title: string; short_title: string; created_at: string }>;
  draft: null | {
    version: number;
    long_title: string;
    long_markdown: string;
    short_title: string;
    short_markdown: string;
    title_candidates: string[];
    topics: string[];
  };
  claims: Array<{
    id: string;
    platform: string;
    claim: string;
    knowledge_ids: string[];
    evidence_ids: string[];
    status: string;
  }>;
};

export type StudioSnapshot = {
  project: StudioProject;
  discovery: DiscoverySnapshot;
  questions: DiscoveryQuestion[];
  prd: PrdVersion | null;
  prd_versions: PrdVersion[];
  prd_validation: PrdValidation | null;
  assumptions: ProductAssumption[];
  release: null | {
    id: string;
    prd_version: number;
    status: string;
    feature_ids: string[];
  };
  execution_units: ExecutionUnit[];
  interactions: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  knowledge: KnowledgeRecord[];
  knowledge_applications: Array<Record<string, unknown>>;
  change_proposals: Array<Record<string, unknown>>;
};

export const studioApi = {
  health: () => request<Health>("/api/v2/health"),
  projects: () => request<{ projects: StudioProject[] }>("/api/v2/projects"),
  createProject: (payload: Record<string, unknown>) =>
    request<{ project: StudioProject; discovery: DiscoverySnapshot; questions: DiscoveryQuestion[] }>(
      "/api/v2/projects",
      {
        method: "POST",
        headers: { "X-Action-ID": crypto.randomUUID() },
        body: JSON.stringify(payload),
      },
    ),
  studio: (project: string) =>
    request<StudioSnapshot>(`/api/v2/projects/${encodeURIComponent(project)}/studio`),
  answer: (project: string, answers: Array<Record<string, string>>) =>
    request<{ project: StudioProject; discovery: DiscoverySnapshot; questions: DiscoveryQuestion[]; prd: PrdVersion | null }>(
      `/api/v2/projects/${encodeURIComponent(project)}/discovery/answers`,
      {
        method: "POST",
        headers: { "X-Action-ID": crypto.randomUUID() },
        body: JSON.stringify({ answers }),
      },
    ),
  discoveryDecision: (
    project: string,
    action: "continue" | "accept_recommendations" | "draft_with_assumptions",
    reason = "",
  ) => request(`/api/v2/projects/${encodeURIComponent(project)}/discovery/decision`, {
    method: "POST",
    headers: { "X-Action-ID": crypto.randomUUID() },
    body: JSON.stringify({ action, reason }),
  }),
  reassessDiscovery: (project: string) =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/discovery/reassess`, {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: "{}",
    }),
  approvePrd: (
    project: string,
    version: number,
    featureIds: string[],
    strategyOverrides: Record<string, string>,
  ) =>
    request<Record<string, unknown>>(
      `/api/v2/projects/${encodeURIComponent(project)}/prd/${version}/approve`,
      {
        method: "POST",
        headers: { "X-Action-ID": crypto.randomUUID() },
        body: JSON.stringify({
          feature_ids: featureIds,
          strategy_overrides: strategyOverrides,
        }),
      },
    ),
  feedbackPrd: (project: string, version: number, feedback: string) =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/prd/${version}/feedback`, {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: JSON.stringify({ feedback }),
    }),
  revalidatePrd: (project: string, version: number) =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/prd/${version}/revalidate`, {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: "{}",
    }),
  resolvePrdAssumption: (
    project: string, version: number, assumption: string, revision: number,
    status: "accepted" | "rejected" | "replaced", resolution: string,
  ) => request(
    `/api/v2/projects/${encodeURIComponent(project)}/prd/${version}/assumptions/${encodeURIComponent(assumption)}/resolve`,
    {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: JSON.stringify({ revision, status, resolution }),
    },
  ),
  proposeChange: (project: string, change: string) =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/changes`, {
      method: "POST",
      headers: { "X-Action-ID": crypto.randomUUID() },
      body: JSON.stringify({ request: change }),
    }),
  setStrategy: (project: string, feature: string, strategy: string, reason: string) =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/features/${encodeURIComponent(feature)}/strategy`, {
      method: "PUT",
      body: JSON.stringify({ strategy, reason }),
    }),
  resolveInteraction: (id: string, revision: number, response: string) =>
    request(`/api/v2/interactions/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body: JSON.stringify({ revision, response }),
    }),
  projectAction: (project: string, action: "pause" | "resume" | "stop") =>
    request(`/api/v2/projects/${encodeURIComponent(project)}/${action}`, {
      method: "POST",
      body: "{}",
    }),
  events: (project: string, after = 0) =>
    request<{ events: Activity[] }>(
      `/api/v2/projects/${encodeURIComponent(project)}/events?after=${after}`,
    ),
  jobs: () => request<{ jobs: Job[] }>("/api/v2/runtime/jobs"),
  cancelJob: (id: string) =>
    request<Job>(`/api/v2/runtime/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      body: "{}",
    }),
  knowledge: (query = "") =>
    request<{ records: KnowledgeRecord[] }>(
      `/api/v2/knowledge/search?q=${encodeURIComponent(query)}&limit=50`,
    ),
  projectKnowledge: (project: string) =>
    request<{ records: KnowledgeRecord[]; applications: Array<Record<string, unknown>> }>(
      `/api/v2/projects/${encodeURIComponent(project)}/knowledge`,
    ),
  knowledgeFeedback: (
    id: string,
    payload: Record<string, unknown>,
  ) => request(`/api/v2/knowledge/records/${encodeURIComponent(id)}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  sourceSuggestions: (projectIds: string[], query = "") =>
    request<{ projects: StudioProject[]; knowledge: KnowledgeRecord[] }>(
      "/api/v2/articles/source-suggestions",
      { method: "POST", body: JSON.stringify({ project_ids: projectIds, query }) },
    ),
  createSourcePack: (
    projectIds: string[],
    knowledgeIds: string[],
    replacements: Record<string, string> = {},
  ) => request<Record<string, unknown>>("/api/v2/articles/source-packs", {
    method: "POST",
    body: JSON.stringify({ project_ids: projectIds, knowledge_ids: knowledgeIds, replacements }),
  }),
  confirmSourcePack: (id: string, revision: number) =>
    request<Record<string, unknown>>(`/api/v2/articles/source-packs/${encodeURIComponent(id)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ revision }),
    }),
  articles: () => request<{ articles: Article[] }>("/api/v2/articles"),
  article: (id: string, version?: number) => request<Article>(`/api/v2/articles/${encodeURIComponent(id)}${version ? `?version=${version}` : ""}`),
  generateArticle: (brief: Record<string, unknown>, sourcePackId: string, modelProfileId = "") =>
    request<Article>("/api/v2/articles", {
      method: "POST",
      body: JSON.stringify({ brief, source_pack_id: sourcePackId, model_profile_id: modelProfileId }),
    }),
  updateArticle: (id: string, version: number, patch: Record<string, unknown>) =>
    request<Article>(`/api/v2/articles/${encodeURIComponent(id)}/drafts/${version}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  regenerateArticle: (id: string, version: number, platform: string, instructions = "") =>
    request<Article>(`/api/v2/articles/${encodeURIComponent(id)}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ version, platform, instructions }),
    }),
  exportArticle: async (id: string, platform: "long" | "short", format: "markdown" | "html" | "text") => {
    const response = await fetch(`/api/v2/articles/${encodeURIComponent(id)}/export`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, format }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `导出失败（${response.status}）`);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || `article.${format === "markdown" ? "md" : format}`;
    return { content: await response.text(), filename, media_type: response.headers.get("Content-Type") || "text/plain" };
  },
  articleModels: () =>
    request<{ profiles: ArticleModelProfile[] }>("/api/v2/settings/article-models"),
  saveArticleModel: (payload: Record<string, unknown>, id = "") =>
    request<ArticleModelProfile>(
      id ? `/api/v2/settings/article-models/${encodeURIComponent(id)}` : "/api/v2/settings/article-models",
      { method: id ? "PUT" : "POST", body: JSON.stringify(payload) },
    ),
  deleteArticleModel: (id: string) =>
    request(`/api/v2/settings/article-models/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testArticleModel: (id: string) =>
    request<{ connected: boolean; response: string }>(
      `/api/v2/settings/article-models/${encodeURIComponent(id)}/test`,
      { method: "POST", body: "{}" },
    ),
  testRuntime: () => request<RuntimeProbe>("/api/v2/settings/runtime/test", {
    method: "POST",
    body: "{}",
  }),
};
