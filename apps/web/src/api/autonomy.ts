// API client for Phase 5 autonomy endpoints

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) return null as T;
  return JSON.parse(text) as T;
}

// ---- Types ----

export interface CheckpointGateConfig {
  after_every_run: boolean;
  after_every_n_runs: number | null;
  before_hardware_escalation: boolean;
  before_result_promotion: boolean;
  before_network_execution: boolean;
}

export interface AutonomyPolicy {
  mode: "supervised" | "autonomous";
  max_total_runs: number | null;
  max_wall_clock_hours: number | null;
  max_runs_per_hypothesis: number | null;
  max_wall_time_per_run_s: number | null;
  summary_interval: number;
  checkpoint_gates: CheckpointGateConfig;
}

export interface AutonomyBudget {
  id: string;
  cycle_id: string;
  total_runs: number;
  wall_clock_elapsed_s: number;
  runs_per_hypothesis: Record<string, number>;
  started_at: string;
  last_run_completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LoopDecision {
  id: string;
  cycle_id: string;
  charter_id: string;
  run_record_id: string;
  recommendation_id: string;
  iteration_number: number;
  decision: string;
  gate_triggered: string | null;
  budget_snapshot: Record<string, unknown>;
  hypothesis_card_id: string | null;
  next_hypothesis_card_id: string | null;
  next_action: string | null;
  context_summary_path: string | null;
  reasoning: string;
  created_at: string;
}

// ---- API calls ----

export async function fetchAutonomyPolicy(cycleId: string): Promise<AutonomyPolicy> {
  return apiFetch<AutonomyPolicy>(`/cycles/${cycleId}/autonomy/policy`);
}

export async function updateAutonomyPolicy(
  cycleId: string,
  updates: Partial<AutonomyPolicy>,
): Promise<AutonomyPolicy> {
  return apiFetch<AutonomyPolicy>(`/cycles/${cycleId}/autonomy/policy`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export async function fetchAutonomyBudget(
  cycleId: string,
): Promise<AutonomyBudget | null> {
  return apiFetch<AutonomyBudget | null>(`/cycles/${cycleId}/autonomy/budget`);
}

export async function fetchLoopDecisions(cycleId: string): Promise<LoopDecision[]> {
  return apiFetch<LoopDecision[]>(`/cycles/${cycleId}/autonomy/decisions`);
}

export async function resumeAutonomyGate(
  cycleId: string,
): Promise<{ resumed_job_id: string }> {
  return apiFetch<{ resumed_job_id: string }>(
    `/cycles/${cycleId}/autonomy/resume`,
    { method: "POST" },
  );
}

export async function stopAutonomyLoop(
  cycleId: string,
): Promise<{ status: string; cycle_status: string }> {
  return apiFetch<{ status: string; cycle_status: string }>(
    `/cycles/${cycleId}/autonomy/stop`,
    { method: "POST" },
  );
}
