import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import {
  useDiscoveryPapers,
  useDiscoveryProfile,
  useDiscoverySession,
  useTriagePaper,
} from "../../../api/hooks";
import EventStream from "../../../components/EventStream";
import Icon from "../../../components/Icon";
import StatusBadge from "../../../components/StatusBadge";

export const Route = createFileRoute("/discovery/$sessionId/")({
  component: DiscoverySessionPage,
});

function DiscoverySessionPage() {
  const { sessionId } = Route.useParams();
  const session = useDiscoverySession(sessionId);
  const profile = useDiscoveryProfile(sessionId);
  const [view, setView] = useState<"stable" | "discovery">("stable");
  const allPapers = useDiscoveryPapers(sessionId, { limit: 500 });
  const papers = useDiscoveryPapers(sessionId, { view, limit: 100 });
  const triage = useTriagePaper();

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
  const allItems = allPapers.data?.items ?? [];
  const critique = readObjectField(s.stats, "shortlist_critique");
  const finalizeStats = readObjectField(s.stats, "finalize");
  const stableCount =
    readNumberField(finalizeStats, "stable_view_size") ??
    countViewMembership(allItems, "stable");
  const discoveryCount =
    readNumberField(finalizeStats, "discovery_view_size") ??
    countViewMembership(allItems, "discovery");
  const totalCandidates =
    readNumberField(finalizeStats, "total_cards") ?? allPapers.data?.total ?? 0;

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
          to="/charters/$charterId"
          params={{ charterId: s.charter_id }}
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Charter
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>Discovery session</span>
      </div>

      <div style={{ padding: "28px 40px", maxWidth: 1240 }}>
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
            Discovery session
          </h1>
          <StatusBadge status={s.status} />
        </div>
        <div
          className="mono"
          style={{
            fontSize: 11.5,
            color: "var(--c-ink-3)",
            marginBottom: 20,
          }}
        >
          {s.id}
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
              Discovery session failed
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

        {profile.data && (
          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <div className="section-label" style={{ marginBottom: 6 }}>
              Query
            </div>
            <div
              style={{
                fontSize: 13.5,
                color: "var(--c-ink)",
                whiteSpace: "pre-wrap",
                lineHeight: 1.55,
              }}
            >
              {profile.data.query_text}
            </div>
            {profile.data.notes && (
              <div
                style={{
                  marginTop: 10,
                  fontSize: 12,
                  color: "var(--c-ink-3)",
                  whiteSpace: "pre-wrap",
                }}
              >
                {profile.data.notes}
              </div>
            )}
          </div>
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <Stat label="Stable view" value={stableCount} />
          <Stat label="Discovery view" value={discoveryCount} />
          <Stat label="Total candidates" value={totalCandidates} />
        </div>

        {critique && (
          <div
            className="card"
            style={{
              padding: 14,
              marginBottom: 16,
              borderColor: "var(--c-warn)",
              background: "var(--c-warn-soft)",
            }}
          >
            <div
              className="section-label"
              style={{
                color: "color-mix(in oklch, var(--c-warn) 70%, var(--c-ink))",
                marginBottom: 6,
              }}
            >
              Shortlist critique
            </div>
            {readStringField(critique, "summary") && (
              <div
                style={{
                  fontSize: 13,
                  color: "color-mix(in oklch, var(--c-warn) 30%, var(--c-ink))",
                  marginBottom: 8,
                }}
              >
                {readStringField(critique, "summary")}
              </div>
            )}
            <CritiqueList
              label="Coverage gaps"
              items={readStringList(critique, "coverage_gaps")}
            />
            <CritiqueList
              label="Clustering risks"
              items={readStringList(critique, "clustering_risks")}
            />
            <CritiqueList
              label="Score concerns"
              items={readStringList(critique, "score_concerns")}
            />
          </div>
        )}

        {s.report_artifact_path && (
          <div style={{ marginBottom: 20 }}>
            <Link
              to="/discovery/$sessionId/report"
              params={{ sessionId }}
              style={{
                fontSize: 13,
                color: "var(--c-accent-ink)",
                fontWeight: 500,
              }}
            >
              View discovery report →
            </Link>
          </div>
        )}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            marginBottom: 14,
            gap: 10,
          }}
        >
          <h2
            style={{
              fontSize: 14,
              fontWeight: 600,
              margin: 0,
              letterSpacing: "-0.005em",
            }}
          >
            Papers
          </h2>
          <span
            style={{
              fontSize: 12,
              color: "var(--c-ink-4)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {papers.data?.total ?? 0}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <ViewTab active={view === "stable"} onClick={() => setView("stable")}>
              Stable
            </ViewTab>
            <ViewTab
              active={view === "discovery"}
              onClick={() => setView("discovery")}
            >
              Discovery
            </ViewTab>
          </div>
        </div>

        {papers.isLoading && (
          <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
            Loading papers…
          </div>
        )}

        {papers.data && papers.data.items.length === 0 && (
          <div
            className="card"
            style={{
              padding: 24,
              textAlign: "center",
              color: "var(--c-ink-3)",
              fontSize: 13.5,
            }}
          >
            No papers in the {view} view yet.
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {papers.data?.items.map((card) => (
            <div key={card.id} className="card" style={{ padding: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h3
                    style={{
                      fontSize: 13.5,
                      fontWeight: 600,
                      margin: 0,
                      color: "var(--c-ink)",
                    }}
                  >
                    {card.title}
                  </h3>
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 11.5,
                      color: "var(--c-ink-3)",
                    }}
                  >
                    {(card.authors ?? []).slice(0, 5).join(", ")}
                    {card.year && <> · {card.year}</>}
                    {card.venue && <> · {card.venue}</>}
                  </div>
                </div>
                <div
                  style={{
                    flexShrink: 0,
                    textAlign: "right",
                    fontSize: 11.5,
                    color: "var(--c-ink-3)",
                  }}
                >
                  <div className="tabular">
                    score {(card.final_score ?? 0).toFixed(4)}
                  </div>
                  <div className="mono" style={{ marginTop: 2 }}>
                    {card.source}
                  </div>
                </div>
              </div>
              {card.metadata_analysis &&
                typeof card.metadata_analysis.one_line_summary === "string" && (
                  <div
                    style={{
                      marginTop: 10,
                      fontSize: 12.5,
                      fontStyle: "italic",
                      color: "var(--c-ink-2)",
                    }}
                  >
                    {String(card.metadata_analysis.one_line_summary)}
                  </div>
                )}
              {readStringField(card.metadata_analysis, "escalation_rationale") && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 12,
                    color: "var(--c-ink-2)",
                  }}
                >
                  <span style={{ color: "var(--c-ink)", fontWeight: 500 }}>
                    Escalation:
                  </span>{" "}
                  {readStringField(card.metadata_analysis, "escalation_rationale")}
                </div>
              )}
              {(readNumberField(card.metadata_analysis, "shortlist_fit") !== null ||
                readNumberField(card.metadata_analysis, "relevance_to_problem") !==
                  null) && (
                <div
                  style={{
                    marginTop: 8,
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                    fontSize: 11,
                    color: "var(--c-ink-2)",
                  }}
                >
                  {readNumberField(card.metadata_analysis, "shortlist_fit") !==
                    null && (
                    <span className="chip slate">
                      shortlist fit{" "}
                      {readNumberField(
                        card.metadata_analysis,
                        "shortlist_fit",
                      )!.toFixed(2)}
                    </span>
                  )}
                  {readNumberField(
                    card.metadata_analysis,
                    "relevance_to_problem",
                  ) !== null && (
                    <span className="chip slate">
                      relevance{" "}
                      {readNumberField(
                        card.metadata_analysis,
                        "relevance_to_problem",
                      )!.toFixed(2)}
                    </span>
                  )}
                </div>
              )}
              {readStringList(card.metadata_analysis, "risks_or_caveats")
                .length > 0 && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 12,
                    color: "var(--c-warn)",
                  }}
                >
                  Risks:{" "}
                  {readStringList(
                    card.metadata_analysis,
                    "risks_or_caveats",
                  ).join("; ")}
                </div>
              )}
              {card.abstract && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12.5,
                    color: "var(--c-ink-2)",
                    lineHeight: 1.5,
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: 3,
                    overflow: "hidden",
                  }}
                >
                  {card.abstract}
                </div>
              )}
              <div
                style={{
                  marginTop: 12,
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                }}
              >
                {card.pdf_url && (
                  <a
                    href={card.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--c-accent-ink)" }}
                  >
                    PDF
                  </a>
                )}
                {card.source_url && (
                  <a
                    href={card.source_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--c-accent-ink)" }}
                  >
                    source
                  </a>
                )}
                <span
                  style={{
                    marginLeft: "auto",
                    display: "inline-flex",
                    gap: 4,
                  }}
                >
                  <TriageButton
                    label="Shortlist"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "shortlisted",
                      })
                    }
                  />
                  <TriageButton
                    label="Drop"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "dropped",
                      })
                    }
                  />
                  <TriageButton
                    label="Escalate"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "escalated",
                      })
                    }
                  />
                </span>
                <StatusBadge status={card.triage_status} />
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 28 }}>
          <h2
            style={{
              fontSize: 14,
              fontWeight: 600,
              margin: 0,
              marginBottom: 12,
              letterSpacing: "-0.005em",
            }}
          >
            Live events
          </h2>
          <div className="card" style={{ padding: "14px 16px" }}>
            <EventStream charterId={s.charter_id} />
          </div>
        </div>
      </div>
    </div>
  );
}

function countViewMembership(
  items: { view_membership: string[] | null }[],
  v: string,
) {
  return items.filter((i) => (i.view_membership ?? []).includes(v)).length;
}

function Stat({ label, value }: { label: string; value: number }) {
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
        }}
      >
        {value}
      </div>
    </div>
  );
}

function CritiqueList({
  label,
  items,
}: {
  label: string;
  items: string[];
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: "color-mix(in oklch, var(--c-warn) 70%, var(--c-ink))",
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 2,
          fontSize: 12,
          color: "color-mix(in oklch, var(--c-warn) 30%, var(--c-ink))",
        }}
      >
        {items.join(" · ")}
      </div>
    </div>
  );
}

function readObjectField(
  value: Record<string, unknown> | null,
  key: string,
): Record<string, unknown> | null {
  if (!value) {
    return null;
  }
  const field = value[key];
  return field && typeof field === "object" && !Array.isArray(field)
    ? (field as Record<string, unknown>)
    : null;
}

function readStringField(
  value: Record<string, unknown> | null,
  key: string,
): string | null {
  if (!value) {
    return null;
  }
  return typeof value[key] === "string" ? String(value[key]) : null;
}

function readNumberField(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  if (!value) {
    return null;
  }
  const field = value[key];
  return typeof field === "number" ? field : null;
}

function readStringList(
  value: Record<string, unknown> | null,
  key: string,
): string[] {
  if (!value) {
    return [];
  }
  const field = value[key];
  return Array.isArray(field)
    ? field.filter((item): item is string => typeof item === "string")
    : [];
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="btn sm"
      style={{
        background: active ? "var(--c-ink)" : "var(--c-bg-elev)",
        color: active ? "var(--c-bg)" : "var(--c-ink-2)",
        borderColor: active ? "var(--c-ink)" : "var(--c-line)",
      }}
    >
      {children}
    </button>
  );
}

function TriageButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className="btn sm">
      {label}
    </button>
  );
}
