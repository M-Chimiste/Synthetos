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
  sequence: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  charter_id: string;
  cycle_id: string | null;
  type: string;
  status: string;
  progress: number | null;
  result: unknown;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillDefinition {
  id: string;
  name: string;
  description: string;
  phase: string;
  enabled: boolean;
}

export interface ResearchState {
  charter_id: string;
  charter: Charter;
  cycles: Cycle[];
  active_cycle: Cycle | null;
  papers_count: number;
  hypotheses_count: number;
  experiments_count: number;
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

export function fetchJobs() {
  return apiFetch<PaginatedResponse<Job>>("/jobs");
}

// ---- Skills ----

export function fetchSkills() {
  return apiFetch<PaginatedResponse<SkillDefinition>>("/skills");
}

export function discoverSkills() {
  return apiFetch<{ discovered: number }>("/skills/discover", {
    method: "POST",
  });
}
