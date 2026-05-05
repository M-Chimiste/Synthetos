// Calm Console status mapping. Restrained 5-tone palette (ok / accent / err /
// warn / slate + violet) applied via tokens.css `.chip` classes.

const STATUS_TONE: Record<string, string> = {
  active: "ok",
  running: "ok",
  succeeded: "accent",
  completed: "accent",
  closed: "accent",
  failed: "err",
  error: "err",
  cancelled: "slate",
  pending: "warn",
  queued: "warn",
  paused: "warn",
  claimed: "warn",
  draft: "slate",
  archived: "slate",
  created: "slate",
  planning: "violet",
  discovering: "violet",
  analyzing: "violet",
  experimenting: "accent",
  verifying: "violet",
  reporting: "accent",
  discovery_ready: "violet",
  discovery_screened: "violet",
  analysis_ready: "violet",
  evidence_ready: "violet",
  portfolio_ready: "accent",
  protocol_ready: "accent",
  loop_deciding: "violet",
  compiled: "accent",
  selected: "accent",
  deferred: "slate",
  rejected: "err",
  promising: "ok",
  stalled: "warn",
  deprioritized: "slate",
  validated: "ok",
  candidate: "slate",
  auto: "ok",
  curated: "accent",
  deprecated: "slate",
  autonomous: "violet",
  supervised: "slate",
  advancing: "ok",
  regressing: "err",
  noisy: "warn",
  breakthrough: "accent",
  disabled: "slate",
  continue_current: "ok",
  parameter_variation: "accent",
  hypothesis_pivot: "violet",
  mechanical_recovery: "warn",
  stop_gate: "warn",
  halt: "slate",
};

export function statusTone(status: string): string {
  return STATUS_TONE[status.toLowerCase()] ?? "slate";
}

export default function StatusBadge({
  status,
  className = "",
}: {
  status: string;
  className?: string;
}) {
  return (
    <span className={`chip ${statusTone(status)} ${className}`.trim()}>
      {status}
    </span>
  );
}
