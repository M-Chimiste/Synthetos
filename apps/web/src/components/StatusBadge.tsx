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
