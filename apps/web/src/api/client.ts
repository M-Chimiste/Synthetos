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
