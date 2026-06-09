import { createFileRoute, Link } from "@tanstack/react-router";
import { useCharters, useCycles } from "../../api/hooks";
import type { Charter } from "../../api/client";
import StatusBadge from "../../components/StatusBadge";
import PipelineRail from "../../components/PipelineRail";
import { progressFromCycleStatus } from "../../components/cycleProgress";

export const Route = createFileRoute("/charters/")({
  component: CharterListPage,
});

function CharterListPage() {
  const { data, isLoading, error } = useCharters();
  const charters = data?.items ?? [];

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 20,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.015em",
              margin: 0,
            }}
          >
            Charters
          </h1>
          <div
            style={{
              color: "var(--c-ink-3)",
              fontSize: 13.5,
              marginTop: 4,
            }}
          >
            Research mandates, each unfolding across cycles.
          </div>
        </div>
        <Link to="/charters/new" className="btn primary">
          + New charter
        </Link>
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
          Failed to load charters: {error.message}
        </div>
      )}

      {isLoading && (
        <div
          style={{
            padding: "16px 0",
            color: "var(--c-ink-3)",
            fontSize: 13,
          }}
        >
          Loading charters…
        </div>
      )}

      {!isLoading && charters.length === 0 && (
        <div
          className="card"
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--c-ink-3)",
          }}
        >
          <p style={{ margin: 0 }}>No charters yet.</p>
          <Link
            to="/charters/new"
            style={{
              marginTop: 8,
              display: "inline-block",
              color: "var(--c-accent-ink)",
            }}
          >
            Create your first charter
          </Link>
        </div>
      )}

      {charters.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 220px 120px 90px",
              padding: "10px 16px",
              borderBottom: "1px solid var(--c-line)",
              fontSize: 11,
              color: "var(--c-ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 500,
            }}
          >
            <span>Title</span>
            <span>Pipeline</span>
            <span>Status</span>
            <span>Created</span>
          </div>
          {charters.map((c, i) => (
            <CharterRow
              key={c.id}
              charter={c}
              last={i === charters.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CharterRow({ charter, last }: { charter: Charter; last: boolean }) {
  const cyclesQuery = useCycles(charter.id);
  const latest = cyclesQuery.data?.items[0];

  return (
    <Link
      to="/charters/$charterId"
      params={{ charterId: charter.id }}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 220px 120px 90px",
        padding: "14px 16px",
        borderBottom: last ? "none" : "1px solid var(--c-line-soft)",
        alignItems: "center",
        cursor: "pointer",
        fontSize: 13.5,
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <div>
        <div style={{ fontWeight: 500 }}>{charter.title}</div>
        <div
          className="mono"
          style={{
            fontSize: 11,
            color: "var(--c-ink-4)",
            marginTop: 2,
          }}
        >
          {charter.id}
        </div>
      </div>
      {latest ? (
        <PipelineRail
          progress={progressFromCycleStatus(latest.status)}
          showLabels={false}
          compact
        />
      ) : (
        <span style={{ color: "var(--c-ink-4)", fontSize: 12 }}>
          {cyclesQuery.isLoading ? "…" : "No cycle yet"}
        </span>
      )}
      <StatusBadge status={charter.status} />
      <span style={{ color: "var(--c-ink-3)", fontSize: 12 }}>
        {new Date(charter.created_at).toLocaleDateString()}
      </span>
    </Link>
  );
}
