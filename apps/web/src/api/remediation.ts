// API client for Phase 4 remediation, signal, frontier, and recommendation endpoints

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function apiFetch<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ---- Types ----

export interface RemediationAction {
  id: string;
  run_record_id: string;
  retry_run_id: string | null;
  charter_id: string;
  cycle_id: string;
  experiment_spec_id: string;
  failure_class: string;
  strategy: string;
  strategy_tier: string;
  action_detail: Record<string, unknown> | null;
  outcome: string;
  attempt_number: number;
  max_attempts: number;
  reasoning: string | null;
  created_at: string;
}

export interface DirectionalSignal {
  id: string;
  run_record_id: string;
  charter_id: string;
  cycle_id: string;
  experiment_spec_id: string;
  signal: string;
  primary_metric_name: string;
  primary_metric_value: number;
  primary_metric_delta: number | null;
  primary_metric_direction: string;
  constraint_metrics: Array<{
    name: string;
    value: number;
    within_bounds: boolean;
  }> | null;
  history_window: Array<{
    run_id: string;
    value: number;
    created_at: string | null;
  }> | null;
  reasoning: string;
  created_at: string;
}

export interface MetricFrontier {
  id: string;
  charter_id: string;
  hypothesis_card_id: string;
  primary_metric_name: string;
  primary_metric_direction: string;
  best_run_id: string;
  best_experiment_spec_id: string;
  best_metric_value: number;
  best_achieved_at: string;
  total_runs: number;
  successful_runs: number;
  runs_since_improvement: number;
  updated_at: string;
  created_at: string;
}

export interface RunRecommendation {
  id: string;
  run_record_id: string;
  charter_id: string;
  cycle_id: string;
  experiment_spec_id: string;
  recommendation_type: string;
  action: string;
  reasoning: string;
  inputs_summary: Record<string, unknown> | null;
  created_at: string;
}

export interface RunLineage {
  run_ids: string[];
  remediation_actions: RemediationAction[];
}

// ---- API calls ----

export async function fetchRunRemediation(
  runId: string
): Promise<RemediationAction[]> {
  return apiFetch<RemediationAction[]>(`/runs/${runId}/remediation`);
}

export async function fetchRunSignal(
  runId: string
): Promise<DirectionalSignal | null> {
  return apiFetch<DirectionalSignal | null>(`/runs/${runId}/signal`);
}

export async function fetchRunRecommendation(
  runId: string
): Promise<RunRecommendation | null> {
  return apiFetch<RunRecommendation | null>(`/runs/${runId}/recommendation`);
}

export async function fetchRunLineage(runId: string): Promise<RunLineage> {
  return apiFetch<RunLineage>(`/runs/${runId}/lineage`);
}

export async function fetchSpecSignalHistory(
  specId: string
): Promise<DirectionalSignal[]> {
  return apiFetch<DirectionalSignal[]>(`/specs/${specId}/signal-history`);
}

export async function fetchHypothesisFrontier(
  cardId: string
): Promise<MetricFrontier | null> {
  return apiFetch<MetricFrontier | null>(`/hypotheses/${cardId}/frontier`);
}

export async function fetchCharterFrontiers(
  charterId: string
): Promise<MetricFrontier[]> {
  return apiFetch<MetricFrontier[]>(`/charters/${charterId}/frontiers`);
}
