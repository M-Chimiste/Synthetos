import { statusTone } from "./statusTone";

export default function StatusDot({
  status,
  pulse = false,
}: {
  status: string;
  pulse?: boolean;
}) {
  return (
    <span className={`dot ${statusTone(status)} ${pulse ? "pulse" : ""}`} />
  );
}
