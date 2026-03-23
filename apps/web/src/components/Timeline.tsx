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
        </div>
      ))}
    </div>
  );
}
