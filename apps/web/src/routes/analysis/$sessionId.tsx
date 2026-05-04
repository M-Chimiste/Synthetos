import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  fetchAnalysisReport,
  fetchAnalysisSession,
  fetchChunks,
  fetchCoverage,
  fetchGraphEdges,
  fetchGraphNodes,
  fetchIngestedDocument,
} from "../../api/analysis";
import Icon from "../../components/Icon";
import Markdown from "../../components/Markdown";
import StatusBadge from "../../components/StatusBadge";

export const Route = createFileRoute("/analysis/$sessionId")({
  component: AnalysisDetail,
});

type Tab = "overview" | "chunks" | "graph" | "coverage" | "report";

function AnalysisDetail() {
  const { sessionId } = Route.useParams();
  const [tab, setTab] = useState<Tab>("overview");

  const session = useQuery({
    queryKey: ["analysis", "session", sessionId],
    queryFn: () => fetchAnalysisSession(sessionId),
    refetchInterval: 3_000,
  });
  const document = useQuery({
    queryKey: ["analysis", "document", sessionId],
    queryFn: () => fetchIngestedDocument(sessionId).catch(() => null),
    enabled: !!sessionId,
  });
  const coverage = useQuery({
    queryKey: ["analysis", "coverage", sessionId],
    queryFn: () => fetchCoverage(sessionId).catch(() => null),
    enabled: !!sessionId,
  });
  const chunks = useQuery({
    queryKey: ["analysis", "chunks", sessionId],
    queryFn: () => fetchChunks(sessionId, { limit: 50 }),
    enabled: !!sessionId,
  });
  const nodes = useQuery({
    queryKey: ["analysis", "nodes", sessionId],
    queryFn: () => fetchGraphNodes(sessionId, { limit: 100 }),
    enabled: !!sessionId,
  });
  const edges = useQuery({
    queryKey: ["analysis", "edges", sessionId],
    queryFn: () => fetchGraphEdges(sessionId, { limit: 100 }),
    enabled: !!sessionId,
  });
  const report = useQuery({
    queryKey: ["analysis", "report", sessionId],
    queryFn: () => fetchAnalysisReport(sessionId).catch(() => null),
    enabled: !!sessionId,
    retry: false,
  });

  if (session.isLoading) {
    return (
      <div style={{ padding: "32px 40px", color: "var(--c-ink-3)" }}>
        Loading session…
      </div>
    );
  }
  if (session.error || !session.data) {
    return (
      <div style={{ padding: "32px 40px" }}>
        <div
          className="card"
          style={{
            padding: 14,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          Failed to load session: {session.error?.message ?? "not found"}
        </div>
      </div>
    );
  }

  const s = session.data;

  return (
    <div>
      <div
        style={{
          padding: "12px 40px",
          borderBottom: "1px solid var(--c-line)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 12.5,
          color: "var(--c-ink-3)",
          background: "var(--c-bg)",
          position: "sticky",
          top: 0,
          zIndex: 5,
        }}
      >
        <Link
          to="/analysis"
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Analysis
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span className="mono" style={{ color: "var(--c-ink)" }}>
          {s.id.slice(0, 12)}
        </span>
      </div>

      <div style={{ padding: "28px 40px", maxWidth: 1240 }}>
        <div style={{ marginBottom: 8 }}>
          <span
            className="mono"
            style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
          >
            {s.id}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 4,
          }}
        >
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.015em",
              margin: 0,
            }}
          >
            Analysis session
          </h1>
          <StatusBadge status={s.status} />
        </div>
        <div
          style={{ fontSize: 13, color: "var(--c-ink-3)", marginBottom: 24 }}
        >
          Paper{" "}
          <span className="mono" style={{ color: "var(--c-ink-2)" }}>
            {s.paper_card_id.slice(0, 12)}
          </span>
          {s.started_at && (
            <> · started {new Date(s.started_at).toLocaleString()}</>
          )}
        </div>

        {(s.status === "failed" || s.error) && (
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
            <div style={{ fontWeight: 500, marginBottom: 4 }}>
              Session failed
            </div>
            {s.error && (
              <pre
                style={{
                  margin: 0,
                  fontSize: 12,
                  whiteSpace: "pre-wrap",
                  fontFamily: "var(--f-mono)",
                }}
              >
                {s.error}
              </pre>
            )}
          </div>
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 12,
            marginBottom: 28,
          }}
        >
          <MiniStat
            label="Chunks"
            value={chunks.data?.total ?? 0}
            loading={chunks.isLoading}
          />
          <MiniStat
            label="Graph nodes"
            value={nodes.data?.total ?? 0}
            loading={nodes.isLoading}
          />
          <MiniStat
            label="Graph edges"
            value={edges.data?.total ?? 0}
            loading={edges.isLoading}
          />
          <MiniStat
            label="Coverage"
            value={
              coverage.data
                ? `${(coverage.data.overall_score * 100).toFixed(0)}%`
                : "—"
            }
            loading={coverage.isLoading}
            tone={
              coverage.data
                ? coverage.data.overall_score >= 0.8
                  ? "ok"
                  : coverage.data.overall_score >= 0.5
                    ? "warn"
                    : "err"
                : undefined
            }
          />
        </div>

        <div
          style={{
            display: "flex",
            gap: 2,
            borderBottom: "1px solid var(--c-line)",
            marginBottom: 24,
          }}
        >
          {(["overview", "chunks", "graph", "coverage", "report"] as Tab[]).map(
            (t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className="btn ghost"
                style={{
                  borderRadius: 0,
                  padding: "8px 14px",
                  fontSize: 13,
                  borderBottom:
                    tab === t
                      ? "2px solid var(--c-ink)"
                      : "2px solid transparent",
                  color: tab === t ? "var(--c-ink)" : "var(--c-ink-3)",
                  fontWeight: tab === t ? 500 : 400,
                  textTransform: "capitalize",
                }}
              >
                {t}
              </button>
            ),
          )}
        </div>

        {tab === "overview" && (
          <OverviewSection
            session={s}
            documentSourceUrl={document.data?.source_url ?? null}
            documentFetchMethod={document.data?.fetch_method ?? null}
          />
        )}
        {tab === "chunks" && (
          <ChunksSection
            chunks={chunks.data?.items ?? []}
            loading={chunks.isLoading}
            total={chunks.data?.total ?? 0}
          />
        )}
        {tab === "graph" && (
          <GraphSection
            nodes={nodes.data?.items ?? []}
            edges={edges.data?.items ?? []}
            nodesLoading={nodes.isLoading}
            edgesLoading={edges.isLoading}
          />
        )}
        {tab === "coverage" && (
          <CoverageSection
            coverage={coverage.data}
            loading={coverage.isLoading}
          />
        )}
        {tab === "report" && (
          <ReportSection
            markdown={report.data?.markdown ?? null}
            json={report.data?.json ?? null}
            loading={report.isLoading}
          />
        )}
      </div>
    </div>
  );
}

function OverviewSection({
  session,
  documentSourceUrl,
  documentFetchMethod,
}: {
  session: { stats: Record<string, unknown> | null; budget: Record<string, unknown> | null };
  documentSourceUrl: string | null;
  documentFetchMethod: string | null;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 24 }}>
      <div className="card" style={{ padding: 18 }}>
        <div className="section-label" style={{ marginBottom: 8 }}>
          Source document
        </div>
        {documentSourceUrl ? (
          <>
            <div style={{ fontSize: 13, marginBottom: 4 }}>
              <a
                href={documentSourceUrl}
                target="_blank"
                rel="noreferrer"
                style={{ color: "var(--c-accent-ink)" }}
              >
                {documentSourceUrl}
              </a>
            </div>
            <div style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
              Fetch method: {documentFetchMethod ?? "—"}
            </div>
          </>
        ) : (
          <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
            No ingested document yet.
          </div>
        )}
      </div>
      <div className="card" style={{ padding: 18 }}>
        <div className="section-label" style={{ marginBottom: 8 }}>
          Stats
        </div>
        <pre
          style={{
            margin: 0,
            fontSize: 11.5,
            color: "var(--c-ink-2)",
            fontFamily: "var(--f-mono)",
            whiteSpace: "pre-wrap",
            maxHeight: 300,
            overflow: "auto",
          }}
        >
          {JSON.stringify(session.stats ?? {}, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function ChunksSection({
  chunks,
  loading,
  total,
}: {
  chunks: Array<{
    id: string;
    chunk_type: string;
    section_path: string | null;
    ordinal: number;
    content: string;
  }>;
  loading: boolean;
  total: number;
}) {
  if (loading) {
    return <Empty>Loading chunks…</Empty>;
  }
  if (chunks.length === 0) {
    return <Empty>No chunks ingested yet.</Empty>;
  }
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div
        style={{
          padding: "8px 14px",
          borderBottom: "1px solid var(--c-line-soft)",
          fontSize: 11.5,
          color: "var(--c-ink-3)",
        }}
      >
        Showing {chunks.length} of {total}
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {chunks.map((c, i) => (
          <li
            key={c.id}
            style={{
              padding: "12px 14px",
              borderBottom:
                i < chunks.length - 1
                  ? "1px solid var(--c-line-soft)"
                  : "none",
              fontSize: 12.5,
            }}
          >
            <div
              style={{
                display: "flex",
                gap: 8,
                marginBottom: 4,
                fontSize: 11,
                color: "var(--c-ink-4)",
              }}
            >
              <span className="chip slate">{c.chunk_type}</span>
              {c.section_path && (
                <span className="mono">{c.section_path}</span>
              )}
              <span style={{ marginLeft: "auto" }}>#{c.ordinal}</span>
            </div>
            <div
              style={{
                color: "var(--c-ink-2)",
                fontSize: 12.5,
                lineHeight: 1.5,
                maxHeight: 100,
                overflow: "hidden",
              }}
            >
              {c.content.slice(0, 400)}
              {c.content.length > 400 && "…"}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GraphSection({
  nodes,
  edges,
  nodesLoading,
  edgesLoading,
}: {
  nodes: Array<{ id: string; node_type: string; label: string }>;
  edges: Array<{ id: string; edge_type: string; source_node_id: string; target_node_id: string }>;
  nodesLoading: boolean;
  edgesLoading: boolean;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <div className="section-label" style={{ marginBottom: 8 }}>
          Nodes ({nodes.length})
        </div>
        {nodesLoading ? (
          <Empty>Loading nodes…</Empty>
        ) : nodes.length === 0 ? (
          <Empty>No nodes extracted.</Empty>
        ) : (
          <div className="card" style={{ overflow: "hidden", maxHeight: 480 }}>
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                overflowY: "auto",
                maxHeight: 480,
              }}
            >
              {nodes.map((n, i) => (
                <li
                  key={n.id}
                  style={{
                    padding: "8px 12px",
                    borderBottom:
                      i < nodes.length - 1
                        ? "1px solid var(--c-line-soft)"
                        : "none",
                    fontSize: 12.5,
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <span className="chip slate" style={{ fontSize: 10.5 }}>
                    {n.node_type}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>{n.label}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div>
        <div className="section-label" style={{ marginBottom: 8 }}>
          Edges ({edges.length})
        </div>
        {edgesLoading ? (
          <Empty>Loading edges…</Empty>
        ) : edges.length === 0 ? (
          <Empty>No edges extracted.</Empty>
        ) : (
          <div className="card" style={{ overflow: "hidden", maxHeight: 480 }}>
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                overflowY: "auto",
                maxHeight: 480,
              }}
            >
              {edges.map((e, i) => (
                <li
                  key={e.id}
                  style={{
                    padding: "8px 12px",
                    borderBottom:
                      i < edges.length - 1
                        ? "1px solid var(--c-line-soft)"
                        : "none",
                    fontSize: 12,
                    fontFamily: "var(--f-mono)",
                    color: "var(--c-ink-2)",
                  }}
                >
                  <span style={{ color: "var(--c-accent-ink)" }}>
                    {e.edge_type}
                  </span>
                  : {e.source_node_id.slice(0, 8)} → {e.target_node_id.slice(0, 8)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function CoverageSection({
  coverage,
  loading,
}: {
  coverage:
    | {
        section_coverage: Record<string, unknown> | null;
        figure_coverage: Record<string, unknown> | null;
        table_coverage: Record<string, unknown> | null;
        equation_coverage: Record<string, unknown> | null;
        unlinked_artifacts: string[] | null;
        warnings: string[] | null;
        overall_score: number;
      }
    | null
    | undefined;
  loading: boolean;
}) {
  if (loading) return <Empty>Loading coverage diagnostic…</Empty>;
  if (!coverage) return <Empty>No coverage diagnostic available.</Empty>;
  return (
    <div className="card" style={{ padding: 18 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <div className="section-label">Overall</div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 600,
            fontVariantNumeric: "tabular-nums",
            color:
              coverage.overall_score >= 0.8
                ? "var(--c-ok)"
                : coverage.overall_score >= 0.5
                  ? "var(--c-warn)"
                  : "var(--c-err)",
          }}
        >
          {(coverage.overall_score * 100).toFixed(0)}%
        </div>
      </div>
      <CoverageRow label="Sections" data={coverage.section_coverage} />
      <CoverageRow label="Figures" data={coverage.figure_coverage} />
      <CoverageRow label="Tables" data={coverage.table_coverage} />
      <CoverageRow label="Equations" data={coverage.equation_coverage} />
      {coverage.warnings && coverage.warnings.length > 0 && (
        <>
          <div className="section-label" style={{ marginTop: 14, marginBottom: 6 }}>
            Warnings
          </div>
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
              fontSize: 12.5,
              color: "var(--c-warn)",
            }}
          >
            {coverage.warnings.map((w, i) => (
              <li key={i} style={{ padding: "2px 0" }}>
                · {w}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function CoverageRow({
  label,
  data,
}: {
  label: string;
  data: Record<string, unknown> | null;
}) {
  if (!data) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{ fontSize: 12, color: "var(--c-ink-3)", marginBottom: 2 }}
      >
        {label}
      </div>
      <pre
        style={{
          margin: 0,
          fontSize: 11.5,
          color: "var(--c-ink-2)",
          fontFamily: "var(--f-mono)",
          whiteSpace: "pre-wrap",
        }}
      >
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

function ReportSection({
  markdown,
  json,
  loading,
}: {
  markdown: string | null;
  json: Record<string, unknown> | null;
  loading: boolean;
}) {
  if (loading) return <Empty>Loading report…</Empty>;
  if (markdown) {
    return (
      <div className="card" style={{ padding: 24 }}>
        <Markdown>{markdown}</Markdown>
      </div>
    );
  }
  if (json) {
    return (
      <div className="card" style={{ padding: 18 }}>
        <pre
          style={{
            margin: 0,
            fontSize: 11.5,
            color: "var(--c-ink-2)",
            fontFamily: "var(--f-mono)",
            whiteSpace: "pre-wrap",
          }}
        >
          {JSON.stringify(json, null, 2)}
        </pre>
      </div>
    );
  }
  return <Empty>No report yet. Reports appear once analysis completes.</Empty>;
}

function MiniStat({
  label,
  value,
  loading,
  tone,
}: {
  label: string;
  value: number | string;
  loading?: boolean;
  tone?: "ok" | "warn" | "err";
}) {
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div
        style={{ fontSize: 11.5, color: "var(--c-ink-3)", fontWeight: 500 }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          marginTop: 4,
          letterSpacing: "-0.015em",
          fontVariantNumeric: "tabular-nums",
          color:
            tone === "ok"
              ? "var(--c-ok)"
              : tone === "warn"
                ? "var(--c-warn)"
                : tone === "err"
                  ? "var(--c-err)"
                  : "var(--c-ink)",
        }}
      >
        {loading ? "—" : value}
      </div>
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div
      className="card"
      style={{
        padding: 32,
        textAlign: "center",
        color: "var(--c-ink-3)",
        fontSize: 13.5,
      }}
    >
      {children}
    </div>
  );
}
