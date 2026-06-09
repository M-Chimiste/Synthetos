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

export interface CycleRunResult {
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

export interface CycleResultIntrospection {
  cycle_id: string;
  charter_id: string | null;
  goal_id: string | null;
  publication_readiness: "ready" | "needs_review" | "incomplete" | "failed";
  summary: string;
  interpretation: string;
  caveats: string[];
  next_steps: string[];
  completion_report_path: string | null;
  completion_report_json_path: string | null;
  introspection_markdown_path: string | null;
  introspection_json_path: string | null;
  runs: CycleRunResult[];
  metrics: Record<string, unknown[]>;
  model_artifacts: RunArtifact[];
  remediation_history: Array<Record<string, unknown>>;
  generated_at: string;
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

export type ProviderType =
  | "anthropic"
  | "openai"
  | "google"
  | "openai_compatible";

export interface ModelCatalogEntry {
  id: string;
  key: string;
  display_name: string;
  provider_type: ProviderType;
  provider_name: string;
  model: string;
  base_url: string | null;
  default_temperature: number | null;
  default_max_tokens: number | null;
  enabled: boolean;
  notes: string | null;
  last_tested_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModelRoleBinding {
  role: string;
  catalog_entry_id: string;
  temperature: number | null;
  max_tokens: number | null;
  updated_at: string;
}

export interface ModelRoleDefault {
  provider: string;
  provider_type: ProviderType;
  model: string;
  base_url: string | null;
  temperature: number | null;
  max_tokens: number | null;
}

export interface ModelSettingsResponse {
  catalog_entries: ModelCatalogEntry[];
  roles: string[];
  role_bindings: ModelRoleBinding[];
  yaml_defaults: Record<string, ModelRoleDefault>;
}

export interface ModelCatalogEntryPayload {
  key?: string;
  display_name?: string;
  provider_type?: ProviderType;
  provider_name?: string;
  model?: string;
  base_url?: string | null;
  default_temperature?: number | null;
  default_max_tokens?: number | null;
  enabled?: boolean;
  notes?: string | null;
}

export interface ModelRoleBindingPayload {
  catalog_entry_id: string;
  temperature?: number | null;
  max_tokens?: number | null;
}

export interface ModelCatalogTestResponse {
  success: boolean;
  latency_ms: number;
  provider: string;
  model: string;
  error: string | null;
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
  if (res.status === 204) {
    return undefined as T;
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

export function updateCharter(
  id: string,
  data: {
    title?: string;
    description?: string;
    problem_statement?: string;
    status?: string;
  },
) {
  return apiFetch<Charter>(`/charters/${id}`, {
    method: "PATCH",
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

export function fetchCycleIntrospection(id: string) {
  return apiFetch<CycleResultIntrospection>(`/cycles/${id}/introspection`);
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

// ---- Settings ----

export function fetchModelSettings() {
  return apiFetch<ModelSettingsResponse>("/settings/models");
}

export function createModelCatalogEntry(data: ModelCatalogEntryPayload) {
  return apiFetch<ModelCatalogEntry>("/settings/models/catalog", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateModelCatalogEntry(
  id: string,
  data: ModelCatalogEntryPayload,
) {
  return apiFetch<ModelCatalogEntry>(`/settings/models/catalog/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteModelCatalogEntry(id: string) {
  return apiFetch<void>(`/settings/models/catalog/${id}`, {
    method: "DELETE",
  });
}

export function assignModelRole(role: string, data: ModelRoleBindingPayload) {
  return apiFetch<ModelRoleBinding>(`/settings/models/roles/${role}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function testModelCatalogEntry(id: string) {
  return apiFetch<ModelCatalogTestResponse>(
    `/settings/models/catalog/${id}/test`,
    {
      method: "POST",
    },
  );
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

// ---- Patterns (Phase 6) ----

export interface PatternSummary {
  id: string;
  pattern_type: string;
  title: string;
  summary: string;
  trust_tier: string;
  evidence_count: number;
  confidence: number;
  staleness_score: number;
  source_charter_ids: string[];
  last_reinforced_at: string;
}

export interface PatternObservationRead {
  id: string;
  pattern_id: string;
  charter_id: string;
  cycle_id: string;
  source_artifact_type: string;
  source_artifact_id: string;
  contribution: Record<string, unknown> | null;
  observed_at: string;
}

export interface PatternDetail extends PatternSummary {
  structured_body: Record<string, unknown>;
  consolidation_version: number;
  first_observed_at: string;
  last_observed_at: string;
  created_at: string;
  updated_at: string;
  recent_observations: PatternObservationRead[];
}

export interface JobAcceptedResponse {
  job_id: string;
}

export interface PatternListFilters {
  pattern_type?: string;
  trust_tier?: string;
  min_confidence?: number;
  charter_id?: string;
}

export function fetchPatterns(filters: PatternListFilters = {}, offset = 0, limit = 50) {
  const params = new URLSearchParams();
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  if (filters.pattern_type) params.set("pattern_type", filters.pattern_type);
  if (filters.trust_tier) params.set("trust_tier", filters.trust_tier);
  if (filters.min_confidence) params.set("min_confidence", String(filters.min_confidence));
  if (filters.charter_id) params.set("charter_id", filters.charter_id);
  return apiFetch<PaginatedResponse<PatternSummary>>(
    `/patterns?${params.toString()}`,
  );
}

export function fetchPattern(id: string) {
  return apiFetch<PatternDetail>(`/patterns/${id}`);
}

export function consolidatePatterns(body: {
  charter_id?: string;
  pattern_types?: string[];
} = {}) {
  return apiFetch<JobAcceptedResponse>("/patterns/consolidate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function decayPatterns(body: { force?: boolean } = {}) {
  return apiFetch<JobAcceptedResponse>("/patterns/decay", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function approvePattern(
  id: string,
  body: { rationale: string; charter_id?: string; expires_at?: string },
) {
  return apiFetch<unknown>(`/patterns/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function rejectPattern(id: string, body: { rationale: string }) {
  return apiFetch<unknown>(`/patterns/${id}/reject`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateTrustTier(
  id: string,
  body: { trust_tier: string; rationale: string },
) {
  return apiFetch<PatternDetail>(`/patterns/${id}/trust-tier`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
