import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import * as api from "./client";

// ---- Charter hooks ----

export function useCharters() {
  return useQuery({
    queryKey: ["charters"],
    queryFn: () => api.fetchCharters(),
  });
}

export function useCharter(id: string) {
  return useQuery({
    queryKey: ["charters", id],
    queryFn: () => api.fetchCharter(id),
    enabled: !!id,
  });
}

export function useCreateCharter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createCharter,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["charters"] });
    },
  });
}

// ---- Cycle hooks ----

export function useCycles(charterId: string) {
  return useQuery({
    queryKey: ["cycles", charterId],
    queryFn: () => api.fetchCycles(charterId),
    enabled: !!charterId,
  });
}

export function useCreateCycle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createCycle,
    onSuccess: (_data, charterId) => {
      void qc.invalidateQueries({ queryKey: ["cycles", charterId] });
      void qc.invalidateQueries({ queryKey: ["state", charterId] });
    },
  });
}

export function useTransitionCycle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      cycleId,
      targetStatus,
    }: {
      cycleId: string;
      targetStatus: string;
    }) => api.transitionCycle(cycleId, targetStatus),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["cycles"] });
      void qc.invalidateQueries({ queryKey: ["state"] });
    },
  });
}

// ---- State hooks ----

export function useResearchState(charterId: string) {
  return useQuery({
    queryKey: ["state", charterId],
    queryFn: () => api.fetchState(charterId),
    enabled: !!charterId,
  });
}

// ---- Job hooks ----

export function useJobs(cycleId?: string, enabled = true) {
  return useQuery({
    queryKey: ["jobs", cycleId ?? "all"],
    queryFn: () => api.fetchJobs(cycleId),
    enabled,
    refetchInterval: 5_000,
  });
}

// ---- Skill hooks ----

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: api.fetchSkills,
  });
}

export function useDiscoverSkills() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.discoverSkills,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

// ---- Discovery hooks ----

export function useDiscoverySessions(charterId?: string) {
  return useQuery({
    queryKey: ["discovery", "sessions", charterId ?? "all"],
    queryFn: () => api.fetchDiscoverySessions(charterId),
  });
}

export function useDiscoverySession(sessionId: string) {
  return useQuery({
    queryKey: ["discovery", "session", sessionId],
    queryFn: () => api.fetchDiscoverySession(sessionId),
    enabled: !!sessionId,
    refetchInterval: 3_000,
  });
}

export function useDiscoveryProfile(sessionId: string) {
  return useQuery({
    queryKey: ["discovery", "profile", sessionId],
    queryFn: () => api.fetchDiscoveryProfile(sessionId),
    enabled: !!sessionId,
  });
}

export function useDiscoveryPapers(
  sessionId: string,
  opts: {
    view?: "stable" | "discovery";
    triage_status?: string;
    min_score?: number;
    offset?: number;
    limit?: number;
  } = {},
) {
  return useQuery({
    queryKey: ["discovery", "papers", sessionId, opts],
    queryFn: () => api.fetchDiscoveryPapers(sessionId, opts),
    enabled: !!sessionId,
  });
}

export function useStartDiscovery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      charterId,
      body,
    }: {
      charterId: string;
      body: api.CreateDiscoveryRequest;
    }) => api.startDiscovery(charterId, body),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ["discovery", "sessions"] });
      void qc.invalidateQueries({ queryKey: ["state", vars.charterId] });
      void qc.invalidateQueries({ queryKey: ["cycles", vars.charterId] });
    },
  });
}

export function useTriagePaper() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      paperId,
      triageStatus,
      triageReason,
    }: {
      sessionId: string;
      paperId: string;
      triageStatus: string;
      triageReason?: string;
    }) => api.triagePaper(sessionId, paperId, triageStatus, triageReason),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["discovery", "papers", vars.sessionId],
      });
    },
  });
}

export function useDiscoveryReport(sessionId: string) {
  return useQuery({
    queryKey: ["discovery", "report", sessionId],
    queryFn: () => api.fetchDiscoveryReport(sessionId),
    enabled: !!sessionId,
    retry: false,
  });
}
