const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  running: "bg-green-100 text-green-800",
  completed: "bg-blue-100 text-blue-800",
  succeeded: "bg-blue-100 text-blue-800",
  failed: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
  pending: "bg-yellow-100 text-yellow-800",
  queued: "bg-yellow-100 text-yellow-800",
  paused: "bg-gray-100 text-gray-800",
  cancelled: "bg-gray-100 text-gray-600",
  draft: "bg-gray-100 text-gray-600",
  planning: "bg-purple-100 text-purple-800",
  discovering: "bg-indigo-100 text-indigo-800",
  analyzing: "bg-indigo-100 text-indigo-800",
  experimenting: "bg-orange-100 text-orange-800",
  created: "bg-slate-100 text-slate-800",
  claimed: "bg-amber-100 text-amber-800",
  discovery_ready: "bg-indigo-100 text-indigo-800",
  discovery_screened: "bg-indigo-100 text-indigo-800",
  analysis_ready: "bg-sky-100 text-sky-800",
  evidence_ready: "bg-sky-100 text-sky-800",
  portfolio_ready: "bg-orange-100 text-orange-800",
  protocol_ready: "bg-orange-100 text-orange-800",
  verifying: "bg-violet-100 text-violet-800",
  loop_deciding: "bg-fuchsia-100 text-fuchsia-800",
  reporting: "bg-blue-100 text-blue-800",
  archived: "bg-gray-100 text-gray-600",
  // Phase 5 hypothesis lifecycle
  promising: "bg-emerald-100 text-emerald-800",
  stalled: "bg-amber-100 text-amber-800",
  deprioritized: "bg-gray-100 text-gray-600",
  validated: "bg-teal-100 text-teal-800",
  compiled: "bg-sky-100 text-sky-800",
  candidate: "bg-slate-100 text-slate-800",
  selected: "bg-indigo-100 text-indigo-800",
  deferred: "bg-gray-100 text-gray-600",
  rejected: "bg-red-100 text-red-800",
  // Autonomy mode
  autonomous: "bg-purple-100 text-purple-800",
  supervised: "bg-slate-100 text-slate-800",
};

const DEFAULT_COLOR = "bg-gray-100 text-gray-700";

export default function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status.toLowerCase()] ?? DEFAULT_COLOR;
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}
    >
      {status}
    </span>
  );
}
