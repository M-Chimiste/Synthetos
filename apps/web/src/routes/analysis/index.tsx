import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalysisSessions } from "../../api/analysis";
import StatusBadge from "../../components/StatusBadge";
import StatusDot from "../../components/StatusDot";

export const Route = createFileRoute("/analysis/")({
  component: AnalysisIndex,
});

function AnalysisIndex() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis-sessions"],
    queryFn: () => fetchAnalysisSessions({ limit: 50 }),
  });

  const sessions = data?.items ?? [];

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div style={{ marginBottom: 24 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.015em",
            margin: 0,
          }}
        >
          Analysis
        </h1>
        <div
          style={{ color: "var(--c-ink-3)", fontSize: 13.5, marginTop: 4 }}
        >
          {data?.total ?? 0} session{(data?.total ?? 0) === 1 ? "" : "s"} —
          full-text ingestion, structural extraction, and evidence cards.
        </div>
      </div>

      {error && (
        <div
          className="card"
          style={{
            padding: 14,
            marginBottom: 16,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          Failed to load sessions: {error.message}
        </div>
      )}

      {isLoading && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Loading analysis sessions…
        </div>
      )}

      {!isLoading && sessions.length === 0 && (
        <div
          className="card"
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--c-ink-3)",
            fontSize: 13.5,
          }}
        >
          No analysis sessions yet. Trigger one from a discovery session paper.
        </div>
      )}

      {sessions.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "28px 1fr 220px 140px 160px",
              padding: "10px 16px",
              borderBottom: "1px solid var(--c-line)",
              fontSize: 11,
              color: "var(--c-ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 500,
            }}
          >
            <span />
            <span>Session</span>
            <span>Paper</span>
            <span>Status</span>
            <span>Started</span>
          </div>
          {sessions.map((s, i) => (
            <Link
              key={s.id}
              to="/analysis/$sessionId"
              params={{ sessionId: s.id }}
              style={{
                display: "grid",
                gridTemplateColumns: "28px 1fr 220px 140px 160px",
                padding: "12px 16px",
                borderBottom:
                  i < sessions.length - 1
                    ? "1px solid var(--c-line-soft)"
                    : "none",
                alignItems: "center",
                fontSize: 13,
                textDecoration: "none",
                color: "inherit",
              }}
            >
              <StatusDot status={s.status} pulse={s.status === "running"} />
              <span className="mono" style={{ color: "var(--c-ink-2)" }}>
                {s.id.slice(0, 12)}
              </span>
              <span className="mono" style={{ color: "var(--c-ink-3)" }}>
                {s.paper_card_id.slice(0, 12)}
              </span>
              <StatusBadge status={s.status} />
              <span style={{ color: "var(--c-ink-3)", fontSize: 12 }}>
                {s.started_at
                  ? new Date(s.started_at).toLocaleString()
                  : new Date(s.created_at).toLocaleString()}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
