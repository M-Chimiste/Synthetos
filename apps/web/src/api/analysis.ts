// API client for Phase 2 analysis endpoints

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

export interface AnalysisSession {
  id: string;
  cycle_id: string;
  charter_id: string;
  paper_card_id: string;
  status: string;
  budget: Record<string, unknown> | null;
  stats: Record<string, unknown> | null;
  step_log: Array<Record<string, unknown>> | null;
  report_artifact_path: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface IngestedDocument {
  id: string;
  analysis_session_id: string;
  paper_card_id: string;
  fetch_method: string;
  source_url: string;
  normalized_sections: Array<Record<string, unknown>> | null;
  normalized_figures: Array<Record<string, unknown>> | null;
  normalized_tables: Array<Record<string, unknown>> | null;
  normalized_equations: Array<Record<string, unknown>> | null;
  quality_assessment: Record<string, unknown> | null;
  fetch_duration_ms: number | null;
  content_hash: string;
  created_at: string;
}

export interface PaperChunk {
  id: string;
  analysis_session_id: string;
  paper_card_id: string;
  chunk_type: string;
  section_path: string | null;
  ordinal: number;
  content: string;
  content_hash: string;
  chunk_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface GraphNode {
  id: string;
  analysis_session_id: string;
  paper_card_id: string;
  node_type: string;
  label: string;
  description: string | null;
  properties: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  created_at: string;
}

export interface GraphEdge {
  id: string;
  analysis_session_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  properties: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  confidence: number | null;
  created_at: string;
}

export interface CoverageDiagnostic {
  id: string;
  analysis_session_id: string;
  section_coverage: Record<string, unknown> | null;
  figure_coverage: Record<string, unknown> | null;
  table_coverage: Record<string, unknown> | null;
  equation_coverage: Record<string, unknown> | null;
  unlinked_artifacts: string[] | null;
  warnings: string[] | null;
  overall_score: number;
  created_at: string;
}

export interface PaperAnalysisPacket {
  id: string;
  analysis_session_id: string;
  paper_card_id: string;
  charter_id: string;
  summary: string;
  key_contributions: string[] | null;
  methods_used: Array<Record<string, unknown>> | null;
  datasets_referenced: Array<Record<string, unknown>> | null;
  reproducibility_notes: Record<string, unknown> | null;
  graph_summary: Record<string, unknown> | null;
  coverage_snapshot: Record<string, unknown> | null;
  chunk_count: number;
  node_count: number;
  edge_count: number;
  analysis_depth: string;
  created_at: string;
  updated_at: string;
}

export interface PaperReviewArtifact {
  id: string;
  analysis_packet_id: string;
  paper_card_id: string;
  strengths: string[] | null;
  weaknesses: string[] | null;
  open_questions: string[] | null;
  critique: string | null;
  scores: Record<string, number> | null;
  reading_priority: string | null;
  created_at: string;
}

export interface EvidenceCard {
  id: string;
  charter_id: string;
  cycle_id: string;
  paper_card_id: string;
  analysis_packet_id: string | null;
  evidence_type: string;
  claim: string;
  supporting_text: string | null;
  source_chunk_ids: string[] | null;
  source_graph_node_ids: string[] | null;
  confidence: number;
  analysis_depth: string;
  contradiction_flags: Record<string, unknown> | null;
  redundancy_group: string | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface AnalysisSessionStartResponse {
  session: AnalysisSession;
  job_id: string;
}

export interface QARequest {
  question: string;
  max_chunks?: number;
  expand_graph?: boolean;
}

export interface QAResponse {
  answer: string;
  supporting_chunks: Array<Record<string, unknown>>;
  supporting_nodes: Array<Record<string, unknown>>;
  confidence: number;
}

export interface LocateRequest {
  entity_type: string;
  query: string;
}

export interface LocateResponse {
  matches: Array<Record<string, unknown>>;
}

export interface AnalysisReport {
  session_id: string;
  markdown: string | null;
  json: Record<string, unknown> | null;
}

// ---- API functions ----

export function startAnalysis(
  paperCardId: string,
  charterId: string,
  cycleId: string,
  budget: Record<string, unknown> = {},
) {
  return apiFetch<AnalysisSessionStartResponse>(
    `/papers/${paperCardId}/analyze?charter_id=${charterId}&cycle_id=${cycleId}`,
    { method: "POST", body: JSON.stringify({ budget }) },
  );
}

export function fetchAnalysisSessions(opts: {
  charter_id?: string;
  cycle_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.charter_id) params.set("charter_id", opts.charter_id);
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.status) params.set("status", opts.status);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<AnalysisSession>>(
    `/analysis${qs ? `?${qs}` : ""}`,
  );
}

export function fetchAnalysisSession(sessionId: string) {
  return apiFetch<AnalysisSession>(`/analysis/${sessionId}`);
}

export function fetchIngestedDocument(sessionId: string) {
  return apiFetch<IngestedDocument>(`/analysis/${sessionId}/document`);
}

export function fetchChunks(sessionId: string, opts: {
  chunk_type?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.chunk_type) params.set("chunk_type", opts.chunk_type);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<PaperChunk>>(
    `/analysis/${sessionId}/chunks${qs ? `?${qs}` : ""}`,
  );
}

export function fetchGraphNodes(sessionId: string, opts: {
  node_type?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.node_type) params.set("node_type", opts.node_type);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<GraphNode>>(
    `/analysis/${sessionId}/graph/nodes${qs ? `?${qs}` : ""}`,
  );
}

export function fetchGraphEdges(sessionId: string, opts: {
  edge_type?: string;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.edge_type) params.set("edge_type", opts.edge_type);
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<GraphEdge>>(
    `/analysis/${sessionId}/graph/edges${qs ? `?${qs}` : ""}`,
  );
}

export function fetchCoverage(sessionId: string) {
  return apiFetch<CoverageDiagnostic>(`/analysis/${sessionId}/coverage`);
}

export function fetchAnalysisPacket(paperCardId: string) {
  return apiFetch<PaperAnalysisPacket>(
    `/papers/${paperCardId}/analysis-packet`,
  );
}

export function fetchReviewArtifact(paperCardId: string) {
  return apiFetch<PaperReviewArtifact>(`/papers/${paperCardId}/review`);
}

export function askAnalysisQuestion(paperCardId: string, body: QARequest) {
  return apiFetch<QAResponse>(`/papers/${paperCardId}/qa`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function locateAnalysisEntity(paperCardId: string, body: LocateRequest) {
  return apiFetch<LocateResponse>(`/papers/${paperCardId}/locate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchAnalysisReport(sessionId: string) {
  return apiFetch<AnalysisReport>(`/analysis/${sessionId}/report`);
}

export function fetchEvidenceCards(opts: {
  charter_id?: string;
  cycle_id?: string;
  evidence_type?: string;
  min_confidence?: number;
  offset?: number;
  limit?: number;
} = {}) {
  const params = new URLSearchParams();
  if (opts.charter_id) params.set("charter_id", opts.charter_id);
  if (opts.cycle_id) params.set("cycle_id", opts.cycle_id);
  if (opts.evidence_type) params.set("evidence_type", opts.evidence_type);
  if (opts.min_confidence !== undefined)
    params.set("min_confidence", String(opts.min_confidence));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<PaginatedResponse<EvidenceCard>>(
    `/evidence${qs ? `?${qs}` : ""}`,
  );
}

export function fetchEvidenceCard(evidenceId: string) {
  return apiFetch<EvidenceCard>(`/evidence/${evidenceId}`);
}
