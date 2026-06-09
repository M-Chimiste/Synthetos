const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  const text = await res.text();
  if (!text) return null as T;
  return JSON.parse(text) as T;
}

export interface GoalCriterion {
  name: string;
  description: string;
  required: boolean;
  check_type:
    | "completed_run_exists"
    | "metric_present"
    | "metric_threshold"
    | "artifact_exists"
    | "verification_passed"
    | "report_generated";
  params: Record<string, unknown>;
  scope: "attempt" | "cumulative";
}

export interface GoalPolicy {
  max_attempt_cycles: number;
  max_total_runs: number | null;
  max_wall_clock_hours: number | null;
  autonomy: Record<string, unknown>;
  discovery: Record<string, unknown>;
  analysis?: Record<string, unknown>;
  hypothesis?: Record<string, unknown>;
  protocol?: Record<string, unknown>;
  repair?: Record<string, unknown>;
}

export interface ResearchGoal {
  id: string;
  charter_id: string;
  title: string;
  goal_statement: string;
  success_criteria: GoalCriterion[];
  policy: GoalPolicy;
  status: "created" | "running" | "satisfied" | "exhausted" | "stopped" | "failed";
  summary: string | null;
  report_path: string | null;
  report_json_path: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface GoalAttempt {
  id: string;
  goal_id: string;
  charter_id: string;
  cycle_id: string;
  attempt_number: number;
  status: string;
  evaluation: {
    passed?: boolean;
    summary?: string;
    criteria?: Array<{ name: string; passed: boolean; required: boolean }>;
    blocked_reason?: string;
    status_ledger?: {
      json_path?: string;
      markdown_path?: string;
      latest?: {
        kind?: string;
        stage?: string;
        summary?: string;
        outcome?: string;
        created_at?: string;
      } | null;
    };
  } | null;
  report_path: string | null;
  report_json_path: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface GoalCreateRequest {
  charter_id: string;
  title: string;
  goal_statement: string;
  success_criteria: GoalCriterion[];
  policy?: Partial<GoalPolicy>;
}

export interface GoalReport {
  goal_id: string;
  markdown: string | null;
  json: Record<string, unknown> | null;
}

export interface RunArtifact {
  artifact_id: string;
  run_id: string;
  name: string;
  path: string;
  size_bytes: number | null;
  hash: string | null;
  artifact_type: string;
  download_url: string;
}

export interface GoalRunResult {
  run_id: string;
  experiment_spec_id: string;
  attempt_number: number | null;
  cycle_id: string;
  run_number: number;
  status: string;
  title: string | null;
  image_ref: string | null;
  command: string | null;
  gpu_enabled: boolean | null;
  exit_code: number | null;
  metrics: Record<string, unknown>;
  artifacts: RunArtifact[];
  verification_verdict: string | null;
  verification_summary: string | null;
  verification_warnings: string[];
  failure_class: string | null;
  error: string | null;
}

export interface GoalAttemptResult {
  attempt_id: string | null;
  attempt_number: number | null;
  cycle_id: string;
  status: string | null;
  evaluation: Record<string, unknown> | null;
  introspection_markdown_path: string | null;
  introspection_json_path: string | null;
  cycle_report_path: string | null;
  runs: GoalRunResult[];
}

export interface GoalResultSummary {
  goal_id: string;
  charter_id: string;
  title: string;
  status: string;
  publication_readiness: "ready" | "needs_review" | "incomplete" | "failed";
  summary: string;
  interpretation: string;
  caveats: string[];
  next_steps: string[];
  attempts: GoalAttemptResult[];
  metrics: Record<string, unknown[]>;
  model_artifacts: RunArtifact[];
  remediation_history: Array<Record<string, unknown>>;
  generated_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export function fetchGoals(charterId?: string): Promise<PaginatedResponse<ResearchGoal>> {
  const params = new URLSearchParams();
  if (charterId) params.set("charter_id", charterId);
  return apiFetch<PaginatedResponse<ResearchGoal>>(`/goals?${params.toString()}`);
}

export function fetchGoalAttempts(goalId: string): Promise<GoalAttempt[]> {
  return apiFetch<GoalAttempt[]>(`/goals/${goalId}/attempts`);
}

export function fetchGoalReport(goalId: string): Promise<GoalReport> {
  return apiFetch<GoalReport>(`/goals/${goalId}/report`);
}

export function fetchGoalResults(goalId: string): Promise<GoalResultSummary> {
  return apiFetch<GoalResultSummary>(`/goals/${goalId}/results`);
}

export function createGoal(body: GoalCreateRequest): Promise<ResearchGoal> {
  return apiFetch<ResearchGoal>("/goals", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function stopGoal(goalId: string): Promise<ResearchGoal> {
  return apiFetch<ResearchGoal>(`/goals/${goalId}/stop`, { method: "POST" });
}
