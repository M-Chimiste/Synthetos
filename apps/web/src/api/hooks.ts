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

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: api.fetchJobs,
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
