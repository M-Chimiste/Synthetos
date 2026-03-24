import type { TimelineEntry } from "../lib/types";

const CATEGORY_ICONS: Record<string, string> = {
  state_change: "\u25C9",
  operator: "\u2699",
  run: "\u25B6",
  report: "\u2709",
  user_action: "\u270B",
  system: "\u2022",
};

const CATEGORY_COLORS: Record<string, string> = {
  state_change: "#6366f1",
  operator: "#8b5cf6",
  run: "#22c55e",
  report: "#f59e0b",
  user_action: "#3b82f6",
  system: "#6b7280",
};

interface TimelineProps {
  items: TimelineEntry[];
  filterCategory?: string | null;
}

function buildSparklinePoints(values: number[]): string {
  if (values.length === 0) {
    return "";
  }
  if (values.length === 1) {
    return "0,24 100,24";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 24 - ((value - min) / span) * 20 - 2;
      return `${x},${y}`;
    })
    .join(" ");
}

export default function Timeline({ items, filterCategory }: TimelineProps) {
  const filtered = filterCategory
    ? items.filter((item) => item.category === filterCategory)
    : items;

  if (filtered.length === 0) {
    return <div style={{ color: "#6b7280", padding: "1rem" }}>No timeline events.</div>;
  }

  return (
    <div style={{ position: "relative", paddingLeft: "2rem" }}>
      <div
        style={{
          position: "absolute",
          left: "0.75rem",
          top: 0,
          bottom: 0,
          width: "2px",
          background: "#e5e7eb",
        }}
      />
      {filtered.map((entry, idx) => (
        <div
          key={idx}
          data-testid="timeline-entry"
          data-category={entry.category}
          style={{ position: "relative", marginBottom: "1rem", paddingLeft: "0.5rem" }}
        >
          <div
            style={{
              position: "absolute",
              left: "-1.55rem",
              top: "0.15rem",
              width: "1.5rem",
              height: "1.5rem",
              borderRadius: "50%",
              background: CATEGORY_COLORS[entry.category] || "#6b7280",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "0.7rem",
              color: "#fff",
            }}
          >
            {CATEGORY_ICONS[entry.category] || "\u2022"}
          </div>
          <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>
            {new Date(entry.timestamp).toLocaleString()}
          </div>
          <div style={{ fontWeight: 500 }}>{entry.summary}</div>
          {entry.frontier_snapshot ? (
            <div
              data-testid="frontier-progress"
              style={{
                marginTop: "0.6rem",
                border: "1px solid #dbe4ea",
                borderRadius: "0.85rem",
                padding: "0.75rem",
                background:
                  "linear-gradient(135deg, rgba(245,248,255,0.95), rgba(237,249,244,0.95))",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                  marginBottom: "0.5rem",
                }}
              >
                <div>
                  <div style={{ fontSize: "0.72rem", textTransform: "uppercase", color: "#64748b" }}>
                    Frontier Progress
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {entry.frontier_snapshot.metric_name ?? "primary metric"}
                  </div>
                </div>
                {entry.directional_signal ? (
                  <div
                    style={{
                      borderRadius: "999px",
                      padding: "0.2rem 0.6rem",
                      background: "#0f766e",
                      color: "#f8fafc",
                      fontSize: "0.72rem",
                      textTransform: "capitalize",
                    }}
                  >
                    {entry.directional_signal}
                  </div>
                ) : null}
              </div>
              <svg
                viewBox="0 0 100 24"
                preserveAspectRatio="none"
                style={{ width: "100%", height: "2.25rem", display: "block" }}
                aria-label="Frontier sparkline"
              >
                <polyline
                  fill="none"
                  stroke="#0f766e"
                  strokeWidth="2.5"
                  points={buildSparklinePoints(entry.frontier_snapshot.series_tail)}
                />
              </svg>
              <div
                style={{
                  marginTop: "0.5rem",
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  gap: "0.5rem",
                  fontSize: "0.78rem",
                  color: "#475569",
                }}
              >
                <div>
                  <strong>Current:</strong>{" "}
                  {entry.frontier_snapshot.current_value ?? "n/a"}
                </div>
                <div>
                  <strong>Best:</strong> {entry.frontier_snapshot.best_value}
                </div>
                <div>
                  <strong>Runs Since Improvement:</strong>{" "}
                  {entry.frontier_snapshot.runs_since_improvement}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
