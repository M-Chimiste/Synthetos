// API client for Synthetos backend

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

// ---- Types ----

export interface Charter {
  id: string;
  title: string;
  description: string;
  problem_statement: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Cycle {
  id: string;
  charter_id: string;
  status: string;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface Job {
  id: string;
  cycle_id: string | null;
  job_type: string;
  status: string;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  claimed_by: string | null;
  priority: number;
  created_at: string;
  completed_at: string | null;
}

export interface SkillDefinition {
  id: string;
  skill_id: string;
  version: string;
  phase: string | null;
  trust_tier: string;
  enabled: boolean;
  source_path: string | null;
  discovered_at: string;
}

export interface StateCycleSummary {
  id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface DomainEvent {
  id: string;
  charter_id: string | null;
  cycle_id: string | null;
  event_type: string;
  payload: Record<string, unknown> | null;
  actor_type: string;
  actor_id: string | null;
  created_at: string;
}

export interface ResearchState {
  charter_id: string;
  charter_title: string;
  charter_status: string;
  cycles: StateCycleSummary[];
  active_cycle: StateCycleSummary | null;
  total_events: number;
  total_jobs: number;
  recent_events: DomainEvent[];
}

export interface DiscoverSkillsResponse {
  discovered: number;
  items: SkillDefinition[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ---- Fetch wrapper ----

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ---- Charter ----

export function fetchCharters(offset = 0, limit = 50) {
  return apiFetch<PaginatedResponse<Charter>>(
    `/charters?offset=${offset}&limit=${limit}`,
  );
}

export function fetchCharter(id: string) {
  return apiFetch<Charter>(`/charters/${id}`);
}

export function createCharter(data: {
  title: string;
  description: string;
  problem_statement: string;
}) {
  return apiFetch<Charter>("/charters", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ---- Cycle ----

export function fetchCycles(charterId: string) {
  return apiFetch<PaginatedResponse<Cycle>>(
    `/cycles?charter_id=${charterId}`,
  );
}

export function fetchCycle(id: string) {
  return apiFetch<Cycle>(`/cycles/${id}`);
}

export function createCycle(charterId: string) {
  return apiFetch<Cycle>("/cycles", {
    method: "POST",
    body: JSON.stringify({ charter_id: charterId }),
  });
}

export function transitionCycle(id: string, targetStatus: string) {
  return apiFetch<Cycle>(`/cycles/${id}/transition`, {
    method: "POST",
    body: JSON.stringify({ target_status: targetStatus }),
  });
}

// ---- State ----

export function fetchState(charterId: string) {
  return apiFetch<ResearchState>(`/state/${charterId}`);
}

// ---- Jobs ----

export function fetchJobs(cycleId?: string) {
  const params = new URLSearchParams();
  if (cycleId) params.set("cycle_id", cycleId);
  const qs = params.toString();
  return apiFetch<PaginatedResponse<Job>>(`/jobs${qs ? `?${qs}` : ""}`);
}

// ---- Skills ----

export function fetchSkills() {
  return apiFetch<PaginatedResponse<SkillDefinition>>("/skills");
}

export function discoverSkills() {
  return apiFetch<DiscoverSkillsResponse>("/skills/discover", {
    method: "POST",
  });
}

// ---- Discovery ----

export interface ProblemProfile {
  id: string;
  cycle_id: string;
  query_text: string;
  notes: string;
  source_scope: Record<string, unknown> | null;
  view_preference: string;
  rerank_policy: Record<string, unknown> | null;
  budget: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DiscoverySession {
  id: string;
  cycle_id: string;
  charter_id: string;
  profile_id: string;
  status: string;
  view: string;
  stats: Record<string, unknown> | null;
  step_log: Array<Record<string, unknown>> | null;
  report_artifact_path: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface PaperCard {
  id: string;
  session_id: string;
  charter_id: string;
  source: string;
  external_id: string;
  dedupe_key: string;
  title: string;
  abstract: string;
  authors: string[] | null;
  categories: string[] | null;
  venue: string | null;
  year: number | null;
  published_at: string | null;
  doi: string | null;
  source_url: string | null;
  pdf_url: string | null;
  bm25_score: number | null;
  dense_score: number | null;
  first_stage_score: number | null;
  rerank_score: number | null;
  final_score: number | null;
  view_membership: string[] | null;
  triage_status: string;
  triage_reason: string | null;
  metadata_analysis: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DiscoverySessionStartResponse {
  session: DiscoverySession;
  profile: ProblemProfile;
  job_id: string;
}

export interface CreateDiscoveryRequest {
  query_text: string;
  notes?: string;
  source_scope?: { internal_corpus?: boolean; arxiv_live?: boolean } | null;
  view_preference?: "stable" | "discovery" | "both";
  rerank_policy?: {
    enabled?: boolean;
    top_n?: number;
    budget_seconds?: number;
    model?: string | null;
  };
  budget?: {
    max_internal_results?: number;
    max_external_results?: number;
    analyze_top_n?: number;
  };
}

export function startDiscovery(charterId: string, body: CreateDiscoveryRequest) {
  return apiFetch<DiscoverySessionStartResponse>(
    `/charters/${charterId}/discovery`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function fetchDiscoverySessions(charterId?: string) {
  const params = new URLSearchParams();
  if (charterId) params.set("charter_id", charterId);
  const qs = params.toString();
  return apiFetch<PaginatedResponse<DiscoverySession>>(
    `/discovery${qs ? `?${qs}` : ""}`,
  );
}

export function fetchDiscoverySession(sessionId: string) {
  return apiFetch<DiscoverySession>(`/discovery/${sessionId}`);
}

export function fetchDiscoveryProfile(sessionId: string) {
  return apiFetch<ProblemProfile>(`/discovery/${sessionId}/profile`);
}

export function fetchDiscoveryPapers(
  sessionId: string,
  opts: {
    view?: "stable" | "discovery";
    triage_status?: string;
    min_score?: number;
    offset?: number;
    limit?: number;
  } = {},
) {
  const params = new URLSearchParams();
  if (opts.view) params.set("view", opts.view);
  if (opts.triage_status) params.set("triage_status", opts.triage_status);
  if (opts.min_score !== undefined) params.set("min_score", String(opts.min_score));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<PaperCard>>(
    `/discovery/${sessionId}/papers${qs ? `?${qs}` : ""}`,
  );
}

export function triagePaper(
  sessionId: string,
  paperId: string,
  triageStatus: string,
  triageReason?: string,
) {
  return apiFetch<PaperCard>(
    `/discovery/${sessionId}/papers/${paperId}/triage`,
    {
      method: "POST",
      body: JSON.stringify({
        triage_status: triageStatus,
        triage_reason: triageReason ?? null,
      }),
    },
  );
}

export interface DiscoveryReport {
  session_id: string;
  markdown: string | null;
  json: Record<string, unknown> | null;
}

export function fetchDiscoveryReport(sessionId: string) {
  return apiFetch<DiscoveryReport>(`/discovery/${sessionId}/report`);
}
