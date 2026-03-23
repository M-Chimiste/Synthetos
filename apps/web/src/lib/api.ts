import type {
  CycleDetailResponse,
  CycleSummaryResponse,
  EvidenceListResponse,
  EvidenceSummaryResponse,
  ExperimentSpecListResponse,
  FailurePostmortemDetail,
  HistoricalComparisonResponse,
  HypothesisListResponse,
  LiteratureTriageResponse,
  PaperCardSummary,
  PortfolioRankingResponse,
  ReportDetail,
  RunDetailResponse,
  RunListResponse,
  SkillDetailResponse,
  SkillSummaryResponse,
  VerificationReportDetail,
  VerificationSummaryResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_LAB_API_BASE ?? "http://127.0.0.1:8000";
const API_TOKEN = import.meta.env.VITE_LAB_API_TOKEN ?? "lab-local-admin";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_TOKEN}`,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function listCycles(): Promise<{ items: CycleSummaryResponse[] }> {
  return request("/api/v1/cycles");
}

export function createCycle(payload: Record<string, unknown>): Promise<CycleDetailResponse> {
  return request("/api/v1/cycles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCycle(cycleId: string): Promise<CycleDetailResponse> {
  return request(`/api/v1/cycles/${cycleId}`);
}

export function cycleCommand(cycleId: string, command: string): Promise<CycleDetailResponse> {
  return request(`/api/v1/cycles/${cycleId}/commands`, {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

export function listSkills(): Promise<{ items: SkillSummaryResponse[] }> {
  return request("/api/v1/skills");
}

export function getSkill(skillId: string): Promise<SkillDetailResponse> {
  return request(`/api/v1/skills/${skillId}`);
}

export function getReport(reportId: string): Promise<ReportDetail> {
  return request(`/api/v1/reports/${reportId}`);
}

export function streamUrl(cycleId?: string): string {
  const url = new URL(`${API_BASE}/api/v1/events/stream`);
  if (cycleId) {
    url.searchParams.set("cycle_id", cycleId);
  }
  url.searchParams.set("token", API_TOKEN);
  return url.toString();
}

export function eventSource(cycleId?: string): EventSource {
  return new EventSource(streamUrl(cycleId), { withCredentials: false });
}

export function listPapers(cycleId: string, status?: string): Promise<{ items: PaperCardSummary[]; total: number }> {
  const params = status ? `?status=${status}` : "";
  return request(`/api/v1/cycles/${cycleId}/papers${params}`);
}

export function getLiteratureTriage(cycleId: string): Promise<LiteratureTriageResponse> {
  return request(`/api/v1/cycles/${cycleId}/literature`);
}

export function startIntake(cycleId: string): Promise<CycleDetailResponse> {
  return cycleCommand(cycleId, "start_intake");
}

export function listEvidence(cycleId: string) {
  return request<EvidenceListResponse>(`/api/v1/cycles/${cycleId}/evidence`);
}

export function getEvidenceSummary(cycleId: string) {
  return request<EvidenceSummaryResponse>(`/api/v1/cycles/${cycleId}/evidence/summary`);
}

export function listHypotheses(cycleId: string) {
  return request<HypothesisListResponse>(`/api/v1/cycles/${cycleId}/hypotheses`);
}

export function getPortfolio(cycleId: string) {
  return request<PortfolioRankingResponse>(`/api/v1/cycles/${cycleId}/hypotheses/portfolio`);
}

export function listExperimentSpecs(cycleId: string) {
  return request<ExperimentSpecListResponse>(`/api/v1/cycles/${cycleId}/experiment-specs`);
}

export function startEvidence(cycleId: string) {
  return cycleCommand(cycleId, "start_evidence");
}

export function listRuns(cycleId: string) {
  return request<RunListResponse>(`/api/v1/cycles/${cycleId}/runs`);
}

export function getRun(runId: string) {
  return request<RunDetailResponse>(`/api/v1/runs/${runId}`);
}

export function getVerificationSummary(cycleId: string) {
  return request<VerificationSummaryResponse>(`/api/v1/cycles/${cycleId}/verification`);
}

export function getVerificationReport(reportId: string) {
  return request<VerificationReportDetail>(`/api/v1/verification-reports/${reportId}`);
}

export function getPostmortem(postmortemId: string) {
  return request<FailurePostmortemDetail>(`/api/v1/postmortems/${postmortemId}`);
}

export function getHistoricalComparison(runId: string) {
  return request<HistoricalComparisonResponse>(`/api/v1/runs/${runId}/historical-comparison`);
}

export function createRun(specId: string, executionProfile = "cpu-small", forceStart = false) {
  return request<RunDetailResponse>(`/api/v1/experiment-specs/${specId}/runs`, {
    method: "POST",
    body: JSON.stringify({
      execution_profile: executionProfile,
      force_start: forceStart,
    }),
  });
}

export function runCommand(runId: string, command: "pause" | "cancel" | "retry" | "resume") {
  return request<RunDetailResponse>(`/api/v1/runs/${runId}/commands`, {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

export function runStreamUrl(runId: string): string {
  const url = new URL(`${API_BASE}/api/v1/runs/${runId}/telemetry/stream`);
  url.searchParams.set("token", API_TOKEN);
  return url.toString();
}

export function runEventSource(runId: string): EventSource {
  return new EventSource(runStreamUrl(runId), { withCredentials: false });
}

export function getTimeline(cycleId: string) {
  return request<import("./types").TimelineResponse>(`/api/v1/cycles/${cycleId}/timeline`);
}

export { API_BASE, API_TOKEN };
