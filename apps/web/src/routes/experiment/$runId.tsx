import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  type RunTelemetry,
  controlRun,
  fetchFailurePostmortem,
  fetchRunRecord,
  fetchRunTelemetry,
  fetchVerificationReport,
} from "../../api/experiment";
import {
  fetchRunLineage,
  fetchRunRecommendation,
  fetchRunRemediation,
  fetchRunSignal,
} from "../../api/remediation";
import Icon from "../../components/Icon";
import StatusBadge from "../../components/StatusBadge";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export const Route = createFileRoute("/experiment/$runId")({
  component: RunDetailPage,
});

function RunDetailPage() {
  const { runId } = Route.useParams();
  const qc = useQueryClient();

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRunRecord(runId),
    enabled: !!runId,
    refetchInterval: 3_000,
  });

  const telemetry = useQuery({
    queryKey: ["run-telemetry", runId],
    queryFn: () => fetchRunTelemetry(runId, { limit: 50 }),
    enabled: !!runId,
  });
  const [liveTelemetry, setLiveTelemetry] = useState<RunTelemetry[]>(
    telemetry.data ?? [],
  );

  useEffect(() => {
    setLiveTelemetry(telemetry.data ?? []);
  }, [telemetry.data]);

  useEffect(() => {
    if (!runId) return undefined;
    const source = new EventSource(`${BASE_URL}/runs/${runId}/telemetry/stream`);
    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as RunTelemetry;
        setLiveTelemetry((current) => {
          if (current.some((item) => item.id === parsed.id)) return current;
          return [...current, parsed].slice(-100);
        });
      } catch {
        // Ignore malformed frames and keep the existing tail.
      }
    };
    source.addEventListener("done", () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId]);

  const verification = useQuery({
    queryKey: ["verification", runId],
    queryFn: () => fetchVerificationReport(runId).catch(() => null),
    enabled: !!runId,
  });

  const postmortem = useQuery({
    queryKey: ["postmortem", runId],
    queryFn: () => fetchFailurePostmortem(runId).catch(() => null),
    enabled: !!runId,
  });

  const remediationActions = useQuery({
    queryKey: ["remediation", runId],
    queryFn: () => fetchRunRemediation(runId).catch(() => []),
    enabled: !!runId,
  });

  const lineage = useQuery({
    queryKey: ["run-lineage", runId],
    queryFn: () => fetchRunLineage(runId).catch(() => null),
    enabled: !!runId,
  });

  const signal = useQuery({
    queryKey: ["signal", runId],
    queryFn: () => fetchRunSignal(runId).catch(() => null),
    enabled: !!runId,
  });

  const recommendation = useQuery({
    queryKey: ["recommendation", runId],
    queryFn: () => fetchRunRecommendation(runId).catch(() => null),
    enabled: !!runId,
  });

  const control = useMutation({
    mutationFn: (action: string) => controlRun(runId, action),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["run", runId] });
      void qc.invalidateQueries({ queryKey: ["run-records"] });
    },
  });

  const telemetryItems = useMemo(
    () =>
      [...liveTelemetry].sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp),
      ),
    [liveTelemetry],
  );

  if (run.isLoading) {
    return (
      <div style={{ padding: "32px 40px", color: "var(--c-ink-3)" }}>
        Loading run…
      </div>
    );
  }
  if (run.error) {
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
          Error loading run: {run.error.message}
        </div>
      </div>
    );
  }
  if (!run.data) {
    return (
      <div style={{ padding: "32px 40px", color: "var(--c-ink-3)" }}>
        Run not found.
      </div>
    );
  }

  const r = run.data;
  const isRunning = r.status === "running";
  const isPaused = r.status === "paused";
  const isFailed = r.status === "failed";
  const isCancelled = r.status === "cancelled";
  const lineageRunIds = lineage.data?.run_ids ?? [];
  const currentLineageIndex = lineageRunIds.findIndex((id) => id === runId);
  const previousRunId =
    currentLineageIndex > 0 ? lineageRunIds[currentLineageIndex - 1] : null;
  const nextRunId =
    currentLineageIndex >= 0 && currentLineageIndex < lineageRunIds.length - 1
      ? lineageRunIds[currentLineageIndex + 1]
      : null;

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
          to="/experiment"
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Experiments
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>Run #{r.run_number}</span>
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
            Run #{r.run_number}
          </h1>
          <StatusBadge status={r.status} />
        </div>
        <div
          className="mono"
          style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
        >
          {r.id}
        </div>

        <div
          style={{
            marginTop: 20,
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 14,
            fontSize: 13,
          }}
        >
          <Field label="Image" value={r.image_ref} mono />
          <Field
            label="Exit code"
            value={r.exit_code != null ? String(r.exit_code) : null}
          />
          <Field
            label="Failure class"
            value={r.failure_class}
          />
          <Field label="Command" value={r.command} mono />
        </div>

        {r.error && (
          <div
            className="card"
            style={{
              padding: 14,
              marginTop: 16,
              borderColor: "var(--c-err)",
              color: "var(--c-err)",
              fontSize: 13,
            }}
          >
            <div style={{ fontWeight: 500, marginBottom: 4 }}>Error</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{r.error}</div>
          </div>
        )}

        <div style={{ marginTop: 20, display: "flex", gap: 8 }}>
          {isRunning && (
            <>
              <button
                type="button"
                className="btn"
                style={{
                  background: "var(--c-warn-soft)",
                  borderColor: "transparent",
                  color: "color-mix(in oklch, var(--c-warn) 70%, var(--c-ink))",
                }}
                onClick={() => control.mutate("pause")}
                disabled={control.isPending}
              >
                <Icon name="pause" size={12} /> Pause
              </button>
              <button
                type="button"
                className="btn"
                style={{
                  background: "var(--c-err-soft)",
                  borderColor: "transparent",
                  color: "var(--c-err)",
                }}
                onClick={() => control.mutate("cancel")}
                disabled={control.isPending}
              >
                <Icon name="stop" size={12} /> Cancel
              </button>
            </>
          )}
          {isPaused && (
            <>
              <button
                type="button"
                className="btn"
                style={{
                  background: "var(--c-ok-soft)",
                  borderColor: "transparent",
                  color: "var(--c-ok)",
                }}
                onClick={() => control.mutate("resume")}
                disabled={control.isPending}
              >
                <Icon name="play" size={12} /> Resume
              </button>
              <button
                type="button"
                className="btn"
                style={{
                  background: "var(--c-err-soft)",
                  borderColor: "transparent",
                  color: "var(--c-err)",
                }}
                onClick={() => control.mutate("cancel")}
                disabled={control.isPending}
              >
                <Icon name="stop" size={12} /> Cancel
              </button>
            </>
          )}
          {(isFailed || isCancelled) && (
            <button
              type="button"
              className="btn primary"
              onClick={() => control.mutate("retry")}
              disabled={control.isPending}
            >
              Retry
            </button>
          )}
        </div>

        {r.metrics_output && Object.keys(r.metrics_output).length > 0 && (
          <Section title="Metrics">
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                gap: 8,
              }}
            >
              {Object.entries(r.metrics_output).map(([name, value]) => (
                <div
                  key={name}
                  className="card"
                  style={{ padding: "10px 14px", textAlign: "center" }}
                >
                  <div
                    style={{ fontSize: 11, color: "var(--c-ink-3)" }}
                  >
                    {name}
                  </div>
                  <div
                    className="mono"
                    style={{
                      fontSize: 16,
                      fontWeight: 600,
                      marginTop: 2,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {typeof value === "number"
                      ? value.toFixed(4)
                      : String(value)}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {verification.data && (
          <Section title="Verification">
            <div className="card" style={{ padding: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                  Verdict
                </span>
                <StatusBadge status={verification.data.verdict} />
              </div>
              <div style={{ fontSize: 13, color: "var(--c-ink-2)" }}>
                {verification.data.summary}
              </div>
              {verification.data.warnings?.map((w, i) => (
                <div
                  key={i}
                  style={{
                    marginTop: 6,
                    fontSize: 12.5,
                    color: "var(--c-warn)",
                  }}
                >
                  Warning: {w}
                </div>
              ))}
            </div>
          </Section>
        )}

        {postmortem.data && (
          <Section title="Failure postmortem">
            <div className="card" style={{ padding: 16 }}>
              <Field label="Failure class" value={postmortem.data.failure_class} />
              <Field label="Root cause" value={postmortem.data.root_cause} />
              {postmortem.data.next_step_recommendation && (
                <Field
                  label="Next step"
                  value={postmortem.data.next_step_recommendation}
                />
              )}
            </div>
          </Section>
        )}

        {lineageRunIds.length > 1 && (
          <Section title="Run lineage">
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 12,
                fontSize: 12.5,
                color: "var(--c-ink-3)",
                marginBottom: 10,
              }}
            >
              {previousRunId && (
                <span>
                  Previous retry{" "}
                  <Link
                    to="/experiment/$runId"
                    params={{ runId: previousRunId }}
                    className="mono"
                    style={{ color: "var(--c-accent-ink)" }}
                  >
                    {previousRunId.slice(0, 12)}
                  </Link>
                </span>
              )}
              {nextRunId && (
                <span>
                  Next retry{" "}
                  <Link
                    to="/experiment/$runId"
                    params={{ runId: nextRunId }}
                    className="mono"
                    style={{ color: "var(--c-accent-ink)" }}
                  >
                    {nextRunId.slice(0, 12)}
                  </Link>
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {lineageRunIds.map((lineageRunId) => {
                const isCurrent = lineageRunId === runId;
                return (
                  <Link
                    key={lineageRunId}
                    to="/experiment/$runId"
                    params={{ runId: lineageRunId }}
                    className="btn sm"
                    style={{
                      background: isCurrent
                        ? "var(--c-accent-soft)"
                        : "var(--c-bg-elev)",
                      color: isCurrent
                        ? "var(--c-accent-ink)"
                        : "var(--c-ink-2)",
                      borderColor: isCurrent
                        ? "var(--c-accent)"
                        : "var(--c-line)",
                      fontFamily: "var(--f-mono)",
                    }}
                  >
                    {lineageRunId.slice(0, 12)}
                  </Link>
                );
              })}
            </div>
          </Section>
        )}

        {signal.data && (
          <Section title="Directional signal">
            <div className="card" style={{ padding: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                  Signal
                </span>
                <StatusBadge status={signal.data.signal} />
              </div>
              <div style={{ fontSize: 13 }}>
                <span style={{ color: "var(--c-ink-3)" }}>
                  {signal.data.primary_metric_name}:
                </span>{" "}
                <span
                  className="mono"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {signal.data.primary_metric_value.toFixed(4)}
                </span>
                {signal.data.primary_metric_delta != null && (
                  <span
                    style={{
                      marginLeft: 6,
                      color:
                        signal.data.primary_metric_delta > 0
                          ? "var(--c-ok)"
                          : signal.data.primary_metric_delta < 0
                            ? "var(--c-err)"
                            : "var(--c-ink-3)",
                    }}
                  >
                    ({signal.data.primary_metric_delta > 0 ? "+" : ""}
                    {signal.data.primary_metric_delta.toFixed(4)})
                  </span>
                )}
              </div>
              {signal.data.constraint_metrics &&
                signal.data.constraint_metrics.length > 0 && (
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 12.5,
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 12,
                    }}
                  >
                    {signal.data.constraint_metrics.map((cm) => (
                      <span
                        key={cm.name}
                        style={{
                          color: cm.within_bounds
                            ? "var(--c-ok)"
                            : "var(--c-err)",
                        }}
                      >
                        {cm.name}: {cm.value.toFixed(4)}{" "}
                        {cm.within_bounds ? "✓" : "✗"}
                      </span>
                    ))}
                  </div>
                )}
              <div
                style={{
                  marginTop: 8,
                  fontSize: 12,
                  color: "var(--c-ink-3)",
                }}
              >
                {signal.data.reasoning}
              </div>
            </div>
          </Section>
        )}

        {recommendation.data && (
          <Section title="Recommendation">
            <div className="card" style={{ padding: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                  Type
                </span>
                <StatusBadge status={recommendation.data.recommendation_type} />
              </div>
              <div style={{ fontSize: 13, marginBottom: 6 }}>
                {recommendation.data.action}
              </div>
              <div style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                {recommendation.data.reasoning}
              </div>
            </div>
          </Section>
        )}

        {remediationActions.data && remediationActions.data.length > 0 && (
          <Section title="Remediation history">
            <div
              style={{ display: "flex", flexDirection: "column", gap: 8 }}
            >
              {remediationActions.data.map((a) => (
                <div key={a.id} className="card" style={{ padding: 14 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 12.5,
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>
                      #{a.attempt_number} {a.strategy}
                    </span>
                    <span className="chip slate" style={{ fontSize: 10.5 }}>
                      {a.strategy_tier}
                    </span>
                    <span className="chip slate" style={{ fontSize: 10.5 }}>
                      {a.outcome}
                    </span>
                  </div>
                  {a.reasoning && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12,
                        color: "var(--c-ink-3)",
                      }}
                    >
                      {a.reasoning}
                    </div>
                  )}
                  {a.retry_run_id && (
                    <div style={{ marginTop: 6, fontSize: 12 }}>
                      Retry:{" "}
                      <Link
                        to="/experiment/$runId"
                        params={{ runId: a.retry_run_id }}
                        className="mono"
                        style={{ color: "var(--c-accent-ink)" }}
                      >
                        {a.retry_run_id.slice(0, 12)}
                      </Link>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        <Section title={`Recent telemetry (${telemetryItems.length})`}>
          <div
            className="card"
            style={{
              padding: 12,
              background: "var(--c-panel)",
              fontFamily: "var(--f-mono)",
              fontSize: 11.5,
              color: "var(--c-ink-2)",
              maxHeight: 280,
              overflowY: "auto",
            }}
          >
            {telemetryItems.length === 0 ? (
              <div style={{ color: "var(--c-ink-4)" }}>No telemetry yet.</div>
            ) : (
              telemetryItems.map((t) => {
                const message =
                  (t.payload as Record<string, unknown>).message ??
                  JSON.stringify(t.payload);
                return (
                  <div key={t.id} style={{ padding: "1px 0" }}>
                    <span style={{ color: "var(--c-ink-4)" }}>
                      {new Date(t.timestamp).toLocaleTimeString()}
                    </span>{" "}
                    <span style={{ color: "var(--c-accent-ink)" }}>
                      [{t.event_type}]
                    </span>{" "}
                    {String(message)}
                  </div>
                );
              })
            )}
          </div>
        </Section>

        {r.resource_usage && (
          <Section title="Resource usage">
            <div className="card" style={{ padding: 14 }}>
              <dl
                style={{
                  margin: 0,
                  display: "grid",
                  gridTemplateColumns: "max-content 1fr",
                  columnGap: 16,
                  rowGap: 4,
                  fontSize: 12.5,
                }}
              >
                {Object.entries(r.resource_usage).map(([k, v]) => (
                  <span key={k} style={{ display: "contents" }}>
                    <dt style={{ color: "var(--c-ink-3)" }}>{k}</dt>
                    <dd
                      style={{
                        margin: 0,
                        color: "var(--c-ink)",
                        fontFamily: "var(--f-mono)",
                      }}
                    >
                      {String(v)}
                    </dd>
                  </span>
                ))}
              </dl>
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--c-ink-3)" }}>{label}</div>
      <div
        style={{
          marginTop: 2,
          color: value ? "var(--c-ink)" : "var(--c-ink-4)",
          fontFamily: mono ? "var(--f-mono)" : undefined,
        }}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section style={{ marginTop: 24 }}>
      <h2
        style={{
          fontSize: 13,
          fontWeight: 600,
          margin: 0,
          marginBottom: 10,
          letterSpacing: "-0.005em",
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}
