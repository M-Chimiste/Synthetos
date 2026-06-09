import { statusTone } from "./statusTone";

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
