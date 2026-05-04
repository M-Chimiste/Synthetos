import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  useApprovePattern,
  usePattern,
  useRejectPattern,
  useUpdateTrustTier,
} from "../../api/hooks";
import Icon from "../../components/Icon";

export const Route = createFileRoute("/patterns/$patternId")({
  component: PatternDetailPage,
});

function PatternDetailPage() {
  const { patternId } = Route.useParams();
  const { data, isLoading, error } = usePattern(patternId);
  const approve = useApprovePattern();
  const reject = useRejectPattern();
  const updateTier = useUpdateTrustTier();
  const [rationale, setRationale] = useState("");

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
          to="/patterns"
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Patterns
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>
          {data?.title ?? "Pattern"}
        </span>
      </div>

      <div style={{ padding: "28px 40px", maxWidth: 1240 }}>
        {isLoading && (
          <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
            Loading…
          </div>
        )}
        {error && (
          <div
            className="card"
            style={{
              padding: 14,
              borderColor: "var(--c-err)",
              color: "var(--c-err)",
              fontSize: 13,
            }}
          >
            {error.message}
          </div>
        )}

        {data && (
          <>
            <div style={{ marginBottom: 4 }}>
              <span
                className="mono"
                style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
              >
                {data.id}
              </span>
            </div>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.015em",
                margin: 0,
              }}
            >
              {data.title}
            </h1>

            <div
              style={{
                marginTop: 20,
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 12,
              }}
            >
              <Stat label="Type" value={data.pattern_type.replace(/_/g, " ")} />
              <Stat label="Trust" value={data.trust_tier} />
              <Stat label="Confidence" value={data.confidence.toFixed(3)} />
              <Stat label="Evidence" value={String(data.evidence_count)} />
              <Stat
                label="Charters"
                value={String(data.source_charter_ids.length)}
              />
              <Stat label="Staleness" value={data.staleness_score.toFixed(2)} />
              <Stat
                label="Last reinforced"
                value={new Date(data.last_reinforced_at).toLocaleString()}
              />
              <Stat
                label="Consolidation v"
                value={String(data.consolidation_version)}
              />
            </div>

            <section style={{ marginTop: 28 }}>
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  margin: 0,
                  marginBottom: 10,
                  letterSpacing: "-0.005em",
                }}
              >
                Summary
              </h2>
              <div
                className="card"
                style={{
                  padding: 18,
                  fontSize: 13.5,
                  color: "var(--c-ink-2)",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.55,
                }}
              >
                {data.summary || "(none)"}
              </div>
            </section>

            <section style={{ marginTop: 28 }}>
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  margin: 0,
                  marginBottom: 10,
                  letterSpacing: "-0.005em",
                }}
              >
                Structured body
              </h2>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <pre
                  style={{
                    margin: 0,
                    padding: 14,
                    background: "var(--c-panel)",
                    fontSize: 11.5,
                    color: "var(--c-ink-2)",
                    fontFamily: "var(--f-mono)",
                    whiteSpace: "pre-wrap",
                    overflow: "auto",
                    maxHeight: 360,
                  }}
                >
                  {JSON.stringify(data.structured_body, null, 2)}
                </pre>
              </div>
            </section>

            <section style={{ marginTop: 28 }}>
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  margin: 0,
                  marginBottom: 10,
                  letterSpacing: "-0.005em",
                }}
              >
                Curation
              </h2>
              <div className="card" style={{ padding: 14 }}>
                <textarea
                  rows={3}
                  placeholder="Rationale (required for any action)…"
                  value={rationale}
                  onChange={(e) => setRationale(e.target.value)}
                  style={{
                    width: "100%",
                    border: "1px solid var(--c-line)",
                    background: "var(--c-bg-elev)",
                    color: "var(--c-ink)",
                    borderRadius: "var(--r-md)",
                    padding: "10px 12px",
                    fontSize: 13,
                    fontFamily: "var(--f-sans)",
                    outline: "none",
                    resize: "vertical",
                  }}
                />
                <div
                  style={{
                    marginTop: 10,
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                  }}
                >
                  <button
                    type="button"
                    disabled={!rationale.trim() || approve.isPending}
                    onClick={() =>
                      approve.mutate({
                        id: patternId,
                        rationale: rationale.trim(),
                      })
                    }
                    className="btn"
                    style={{
                      background: "var(--c-ok-soft)",
                      borderColor: "transparent",
                      color: "var(--c-ok)",
                    }}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={!rationale.trim() || reject.isPending}
                    onClick={() =>
                      reject.mutate({
                        id: patternId,
                        rationale: rationale.trim(),
                      })
                    }
                    className="btn"
                    style={{
                      background: "var(--c-err-soft)",
                      borderColor: "transparent",
                      color: "var(--c-err)",
                    }}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={!rationale.trim() || updateTier.isPending}
                    onClick={() =>
                      updateTier.mutate({
                        id: patternId,
                        trust_tier: "curated",
                        rationale: rationale.trim(),
                      })
                    }
                    className="btn"
                  >
                    Mark curated
                  </button>
                  <button
                    type="button"
                    disabled={!rationale.trim() || updateTier.isPending}
                    onClick={() =>
                      updateTier.mutate({
                        id: patternId,
                        trust_tier: "deprecated",
                        rationale: rationale.trim(),
                      })
                    }
                    className="btn"
                  >
                    Deprecate
                  </button>
                </div>
              </div>
            </section>

            <section style={{ marginTop: 28 }}>
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  margin: 0,
                  marginBottom: 10,
                  letterSpacing: "-0.005em",
                }}
              >
                Recent observations
              </h2>
              {data.recent_observations.length === 0 ? (
                <div
                  className="card"
                  style={{
                    padding: 24,
                    textAlign: "center",
                    color: "var(--c-ink-3)",
                    fontSize: 13.5,
                  }}
                >
                  No observations yet.
                </div>
              ) : (
                <div className="card" style={{ overflow: "hidden" }}>
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {data.recent_observations.map((o, i) => (
                      <li
                        key={o.id}
                        style={{
                          padding: "10px 14px",
                          borderBottom:
                            i < data.recent_observations.length - 1
                              ? "1px solid var(--c-line-soft)"
                              : "none",
                          display: "flex",
                          gap: 10,
                          alignItems: "center",
                          fontSize: 12.5,
                        }}
                      >
                        <span
                          className="mono"
                          style={{ fontSize: 11, color: "var(--c-ink-4)" }}
                        >
                          {new Date(o.observed_at).toLocaleString()}
                        </span>
                        <span className="chip slate" style={{ fontSize: 10.5 }}>
                          {o.source_artifact_type}
                        </span>
                        <span
                          className="mono"
                          style={{ color: "var(--c-ink-3)" }}
                        >
                          cycle {o.cycle_id.slice(0, 8)}…
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card" style={{ padding: "12px 14px" }}>
      <div
        style={{
          fontSize: 11,
          color: "var(--c-ink-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 14,
          color: "var(--c-ink)",
          marginTop: 4,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}
