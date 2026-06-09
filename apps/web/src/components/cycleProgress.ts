import type { PhaseKey, PhaseState } from "./PipelineRail";

function cycleStatusToPhaseIndex(status: string): number {
  switch (status) {
    case "created":
      return -1;
    case "discovery_ready":
    case "discovery_screened":
      return 0;
    case "analysis_ready":
    case "evidence_ready":
      return 1;
    case "portfolio_ready":
      return 2;
    case "protocol_ready":
      return 3;
    case "running":
    case "experimenting":
      return 4;
    case "verifying":
      return 5;
    case "loop_deciding":
    case "reporting":
    case "completed":
    case "closed":
      return 6;
    default:
      return -1;
  }
}

export function progressFromCycleStatus(
  status: string,
): Record<PhaseKey, PhaseState> {
  const idx = cycleStatusToPhaseIndex(status);
  const out = {} as Record<PhaseKey, PhaseState>;
  const keys: PhaseKey[] = [
    "discovery",
    "analysis",
    "ideation",
    "protocol",
    "execution",
    "verification",
  ];
  keys.forEach((key, i) => {
    out[key] = i < idx ? "done" : i === idx ? "running" : "pending";
  });
  return out;
}
