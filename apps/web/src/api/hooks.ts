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

export function useUpdateCharter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Parameters<typeof api.updateCharter>[1];
    }) => api.updateCharter(id, data),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: ["charters"] });
      void qc.invalidateQueries({ queryKey: ["charters", vars.id] });
      void qc.invalidateQueries({ queryKey: ["state", vars.id] });
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

// ---- Settings hooks ----

export function useModelSettings() {
  return useQuery({
    queryKey: ["settings", "models"],
    queryFn: api.fetchModelSettings,
  });
}

export function useCreateModelCatalogEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createModelCatalogEntry,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings", "models"] });
    },
  });
}

export function useUpdateModelCatalogEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Parameters<typeof api.updateModelCatalogEntry>[1];
    }) => api.updateModelCatalogEntry(id, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings", "models"] });
    },
  });
}

export function useDeleteModelCatalogEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteModelCatalogEntry,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings", "models"] });
    },
  });
}

export function useAssignModelRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      role,
      data,
    }: {
      role: string;
      data: api.ModelRoleBindingPayload;
    }) => api.assignModelRole(role, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings", "models"] });
    },
  });
}

export function useTestModelCatalogEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.testModelCatalogEntry,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings", "models"] });
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

// ---- Patterns (Phase 6) ----

export function usePatterns(filters: api.PatternListFilters = {}) {
  return useQuery({
    queryKey: ["patterns", filters],
    queryFn: () => api.fetchPatterns(filters),
  });
}

export function usePattern(id: string) {
  return useQuery({
    queryKey: ["patterns", id],
    queryFn: () => api.fetchPattern(id),
    enabled: !!id,
  });
}

export function useConsolidatePatterns() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.consolidatePatterns,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["patterns"] });
    },
  });
}

export function useDecayPatterns() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.decayPatterns,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["patterns"] });
    },
  });
}

export function useApprovePattern() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, rationale }: { id: string; rationale: string }) =>
      api.approvePattern(id, { rationale }),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: ["patterns", vars.id] });
      void qc.invalidateQueries({ queryKey: ["patterns"] });
    },
  });
}

export function useRejectPattern() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, rationale }: { id: string; rationale: string }) =>
      api.rejectPattern(id, { rationale }),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: ["patterns", vars.id] });
      void qc.invalidateQueries({ queryKey: ["patterns"] });
    },
  });
}

export function useUpdateTrustTier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      trust_tier,
      rationale,
    }: {
      id: string;
      trust_tier: string;
      rationale: string;
    }) => api.updateTrustTier(id, { trust_tier, rationale }),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: ["patterns", vars.id] });
      void qc.invalidateQueries({ queryKey: ["patterns"] });
    },
  });
}
