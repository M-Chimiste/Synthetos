import { Fragment } from "react";

export type PhaseState = "pending" | "running" | "done";

export const PHASE_KEYS = [
  "discovery",
  "analysis",
  "ideation",
  "protocol",
  "execution",
  "verification",
] as const;

export type PhaseKey = (typeof PHASE_KEYS)[number];

const PHASE_LABELS: Record<PhaseKey, string> = {
  discovery: "Discovery",
  analysis: "Analysis",
  ideation: "Ideation",
  protocol: "Protocol",
  execution: "Execution",
  verification: "Verification",
};

// Maps a domain cycle status onto the 0-based index of the phase that's
// currently `running`. Everything before that index is `done`, everything
// after is `pending`. Returns -1 for not-yet-started and 6 (out of bounds)
// when the whole pipeline is complete.
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
  PHASE_KEYS.forEach((key, i) => {
    out[key] = i < idx ? "done" : i === idx ? "running" : "pending";
  });
  return out;
}

export default function PipelineRail({
  progress,
  compact = false,
  showLabels = true,
}: {
  progress: Partial<Record<PhaseKey, PhaseState>>;
  compact?: boolean;
  showLabels?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: compact ? 4 : 6 }}>
      {PHASE_KEYS.map((key, i) => {
        const state: PhaseState = progress[key] ?? "pending";
        const isLast = i === PHASE_KEYS.length - 1;
        const dotBg =
          state === "done"
            ? "var(--c-accent)"
            : state === "running"
              ? "var(--c-ok)"
              : "var(--c-line)";
        return (
          <Fragment key={key}>
            <div
              title={`${PHASE_LABELS[key]}: ${state}`}
              style={{ display: "flex", alignItems: "center", gap: 6 }}
            >
              <span
                style={{
                  width: compact ? 7 : 9,
                  height: compact ? 7 : 9,
                  borderRadius: 999,
                  background: dotBg,
                  border:
                    state === "running" ? "2px solid var(--c-ok-soft)" : "none",
                  boxShadow:
                    state === "running" ? "0 0 0 3px var(--c-ok-soft)" : "none",
                  animation:
                    state === "running"
                      ? "calm-pulse 1.8s ease-in-out infinite"
                      : "none",
                  flexShrink: 0,
                  display: "inline-block",
                }}
              />
              {showLabels && !compact && (
                <span
                  style={{
                    fontSize: 11.5,
                    color:
                      state === "pending" ? "var(--c-ink-4)" : "var(--c-ink-2)",
                    fontWeight: state === "running" ? 600 : 400,
                  }}
                >
                  {PHASE_LABELS[key]}
                </span>
              )}
            </div>
            {!isLast && (
              <span
                style={{
                  flex: compact ? "0 0 16px" : "0 0 24px",
                  height: 1,
                  background:
                    state === "done" ? "var(--c-accent)" : "var(--c-line)",
                  opacity: state === "done" ? 0.5 : 1,
                }}
              />
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
