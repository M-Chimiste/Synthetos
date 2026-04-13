// API client for Phase 3 experiment endpoints

import type { PaginatedResponse } from "./client";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ---- Types ----

export interface HypothesisSession {
  id: string;
  cycle_id: string;
  charter_id: string;
  status: string;
  budget: Record<string, unknown> | null;
  stats: Record<string, unknown> | null;
  step_log: Array<Record<string, unknown>> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface HypothesisCard {
  id: string;
  hypothesis_session_id: string;
  charter_id: string;
  cycle_id: string;
  title: string;
  statement: string;
  rationale: string;
  mechanism: string | null;
  supporting_evidence_ids: string[];
  critique: Record<string, unknown> | null;
  novelty_score: number | null;
  feasibility_score: number | null;
  impact_score: number | null;
  rank: number | null;
  status: string;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExperimentSpec {
  id: string;
  hypothesis_card_id: string;
  charter_id: string;
  cycle_id: string;
  title: string;
  description: string;
  baseline: Record<string, unknown>;
  controls: Array<Record<string, unknown>>;
  metrics: Array<Record<string, unknown>>;
  expected_artifacts: Array<Record<string, unknown>>;
  stop_conditions: Array<Record<string, unknown>>;
  code_plan: Record<string, unknown> | null;
  hardware_profile: Record<string, unknown> | null;
  base_image: string | null;
  status: string;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunRecord {
  id: string;
  experiment_spec_id: string;
  parent_run_id: string | null;
  charter_id: string;
  cycle_id: string;
  run_number: number;
  status: string;
  workspace_path: string | null;
  container_id: string | null;
  image_ref: string | null;
  command: string | null;
  exit_code: number | null;
  metrics_output: Record<string, number> | null;
  artifact_manifest: Array<Record<string, unknown>> | null;
  resource_usage: Record<string, unknown> | null;
  failure_class: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunTelemetry {
  id: string;
  run_record_id: string;
  timestamp: string;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface VerificationReport {
  id: string;
  run_record_id: string;
  charter_id: string;
  cycle_id: string;
  verdict: string;
  baseline_comparison: Record<string, unknown> | null;
  artifact_checks: Array<Record<string, unknown>> | null;
  warnings: string[] | null;
  summary: string;
  created_at: string;
}

export interface FailurePostmortem {
  id: string;
  run_record_id: string;
  charter_id: string;
  cycle_id: string;
  failure_class: string;
  root_cause: string;
  contributing_factors: Array<Record<string, unknown>> | null;
  error_trace: string | null;
  next_step_recommendation: string | null;
  lessons: Array<Record<string, unknown>> | null;
  created_at: string;
}

export interface HypothesisSessionStartResponse {
  session: HypothesisSession;
  job_id: string;
}

export interface ExperimentSpecCompileResponse {
  specs: ExperimentSpec[];
  job_id: string;
}

export interface RunStartResponse {
  run: RunRecord;
  job_id: string;
}

// ---- Hypothesis API ----

export function startHypothesisSession(body: {
  cycle_id: string;
  charter_id: string;
  budget?: { max_hypotheses?: number; max_critique_rounds?: number };
}) {
  return apiFetch<HypothesisSessionStartResponse>(
    "/hypotheses/sessions",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function fetchHypothesisSessions(opts: {
  charter_id?: string;
  cycle_id?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.charter_id) params.set("charter_id", opts.charter_id);
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<HypothesisSession>>(
    `/hypotheses/sessions${qs ? `?${qs}` : ""}`,
  );
}

export function fetchHypothesisSession(sessionId: string) {
  return apiFetch<HypothesisSession>(`/hypotheses/sessions/${sessionId}`);
}

export function fetchHypothesisCards(opts: {
  cycle_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.status) params.set("status", opts.status);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<HypothesisCard>>(
    `/hypotheses/cards${qs ? `?${qs}` : ""}`,
  );
}

export function fetchHypothesisCard(cardId: string) {
  return apiFetch<HypothesisCard>(`/hypotheses/cards/${cardId}`);
}

export function updateHypothesisCard(
  cardId: string,
  body: { status?: string; rejection_reason?: string },
) {
  return apiFetch<HypothesisCard>(`/hypotheses/cards/${cardId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

// ---- Protocol API ----

export function compileProtocols(body: {
  cycle_id: string;
  charter_id: string;
  hypothesis_card_ids?: string[];
  hardware_profile?: Record<string, unknown>;
  base_image?: string;
}) {
  return apiFetch<ExperimentSpecCompileResponse>(
    "/protocols/compile",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function fetchExperimentSpecs(opts: {
  cycle_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.status) params.set("status", opts.status);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<ExperimentSpec>>(
    `/protocols/specs${qs ? `?${qs}` : ""}`,
  );
}

export function fetchExperimentSpec(specId: string) {
  return apiFetch<ExperimentSpec>(`/protocols/specs/${specId}`);
}

// ---- Run API ----

export function startRun(body: {
  experiment_spec_id: string;
  gpu_enabled?: boolean;
}) {
  return apiFetch<RunStartResponse>(
    "/runs",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function fetchRunRecords(opts: {
  cycle_id?: string;
  spec_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.spec_id) params.set("spec_id", opts.spec_id);
  if (opts.status) params.set("status", opts.status);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<RunRecord>>(
    `/runs${qs ? `?${qs}` : ""}`,
  );
}

export function fetchRunRecord(runId: string) {
  return apiFetch<RunRecord>(`/runs/${runId}`);
}

export function controlRun(runId: string, action: string) {
  return apiFetch<RunRecord>(`/runs/${runId}/control`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function fetchRunTelemetry(runId: string, opts: {
  since?: string;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.since) params.set("since", opts.since);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<RunTelemetry[]>(
    `/runs/${runId}/telemetry${qs ? `?${qs}` : ""}`,
  );
}

// ---- Verification API ----

export function fetchVerificationReport(runId: string) {
  return apiFetch<VerificationReport>(`/runs/${runId}/verification`);
}

export function fetchFailurePostmortem(runId: string) {
  return apiFetch<FailurePostmortem>(`/runs/${runId}/postmortem`);
}

export function fetchVerificationReports(opts: {
  cycle_id?: string;
  verdict?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.verdict) params.set("verdict", opts.verdict);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<VerificationReport>>(
    `/verifications${qs ? `?${qs}` : ""}`,
  );
}
