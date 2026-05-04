import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  fetchExperimentSpecs,
  fetchHypothesisCards,
  fetchRunRecords,
} from "../../api/experiment";
import {
  fetchCharterFrontiers,
  type MetricFrontier,
} from "../../api/remediation";
import { useCharters } from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";
import StatusDot from "../../components/StatusDot";

export const Route = createFileRoute("/experiment/")({
  component: ExperimentIndex,
});

function ExperimentIndex() {
  const charters = useCharters();
  const [selectedCharter, setSelectedCharter] = useState<string>("");

  // Default to the first charter once they load (and only once).
  useEffect(() => {
    if (!selectedCharter && charters.data?.items.length) {
      setSelectedCharter(charters.data.items[0].id);
    }
  }, [charters.data, selectedCharter]);

  const charterId = selectedCharter || undefined;

  const hypotheses = useQuery({
    queryKey: ["hypothesis-cards", charterId ?? "all"],
    queryFn: () => fetchHypothesisCards({ limit: 20 }),
  });

  // Hypotheses endpoint doesn't filter by charter — do it client-side.
  const filteredHypotheses = useMemo(
    () =>
      (hypotheses.data?.items ?? []).filter(
        (h) => !charterId || h.charter_id === charterId,
      ),
    [hypotheses.data, charterId],
  );

  const specs = useQuery({
    queryKey: ["experiment-specs"],
    queryFn: () => fetchExperimentSpecs({ limit: 20 }),
  });

  const filteredSpecs = useMemo(
    () =>
      (specs.data?.items ?? []).filter(
        (s) => !charterId || s.charter_id === charterId,
      ),
    [specs.data, charterId],
  );

  const runs = useQuery({
    queryKey: ["run-records"],
    queryFn: () => fetchRunRecords({ limit: 20 }),
    refetchInterval: 5_000,
  });

  const filteredRuns = useMemo(
    () =>
      (runs.data?.items ?? []).filter(
        (r) => !charterId || r.charter_id === charterId,
      ),
    [runs.data, charterId],
  );

  const frontiers = useQuery({
    queryKey: ["frontiers", charterId],
    queryFn: () => fetchCharterFrontiers(charterId!),
    enabled: !!charterId,
  });

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 24,
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
            Experiments
          </h1>
          <div
            style={{
              color: "var(--c-ink-3)",
              fontSize: 13.5,
              marginTop: 4,
            }}
          >
            Hypotheses, protocol specs, runs, and metric frontiers.
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12.5,
            color: "var(--c-ink-3)",
          }}
        >
          <span>Charter</span>
          <select
            value={selectedCharter}
            onChange={(e) => setSelectedCharter(e.target.value)}
            style={{
              border: "1px solid var(--c-line)",
              background: "var(--c-bg-elev)",
              color: "var(--c-ink)",
              borderRadius: "var(--r-md)",
              padding: "6px 10px",
              fontSize: 13,
              fontFamily: "var(--f-sans)",
              outline: "none",
            }}
          >
            <option value="">All charters</option>
            {(charters.data?.items ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Section
        title="Hypotheses"
        count={filteredHypotheses.length}
        loading={hypotheses.isLoading}
        empty="No hypotheses yet."
      >
        {filteredHypotheses.map((h, i) => (
          <Row
            key={h.id}
            last={i === filteredHypotheses.length - 1}
            primary={h.title}
            secondary={
              <>
                {h.rank != null ? `#${h.rank}` : "unranked"}
                {h.novelty_score != null && (
                  <>
                    {" · "}
                    N:{h.novelty_score.toFixed(2)} F:
                    {h.feasibility_score?.toFixed(2)} I:
                    {h.impact_score?.toFixed(2)}
                  </>
                )}
              </>
            }
            badge={<StatusBadge status={h.status} />}
          />
        ))}
      </Section>

      <Section
        title="Experiment specs"
        count={filteredSpecs.length}
        loading={specs.isLoading}
        empty="No specs yet."
      >
        {filteredSpecs.map((s, i) => (
          <Row
            key={s.id}
            last={i === filteredSpecs.length - 1}
            primary={s.title}
            secondary={
              <>
                {s.metrics.length} metric{s.metrics.length === 1 ? "" : "s"} ·{" "}
                <span className="mono">{s.base_image || "default image"}</span>
              </>
            }
            badge={<StatusBadge status={s.status} />}
          />
        ))}
      </Section>

      <Section
        title="Runs"
        count={filteredRuns.length}
        loading={runs.isLoading}
        empty="No runs yet."
      >
        {filteredRuns.map((r, i) => (
          <Link
            key={r.id}
            to="/experiment/$runId"
            params={{ runId: r.id }}
            style={{
              display: "grid",
              gridTemplateColumns: "28px 1fr auto",
              gap: 12,
              padding: "12px 16px",
              borderBottom:
                i < filteredRuns.length - 1
                  ? "1px solid var(--c-line-soft)"
                  : "none",
              alignItems: "center",
              fontSize: 13,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            <StatusDot status={r.status} pulse={r.status === "running"} />
            <div style={{ minWidth: 0 }}>
              <div
                style={{ display: "flex", gap: 8, alignItems: "center" }}
              >
                <span style={{ fontWeight: 500 }}>Run #{r.run_number}</span>
                <span
                  className="mono"
                  style={{ color: "var(--c-ink-4)", fontSize: 11.5 }}
                >
                  {r.id.slice(0, 12)}
                </span>
              </div>
              <div
                style={{
                  fontSize: 11.5,
                  color: "var(--c-ink-3)",
                  marginTop: 2,
                }}
              >
                {r.exit_code != null && <>exit {r.exit_code} · </>}
                {r.failure_class && <>{r.failure_class} · </>}
                <span className="mono">
                  {r.image_ref || "no image"}
                </span>
              </div>
              {r.metrics_output && (
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--c-accent-ink)",
                    marginTop: 2,
                  }}
                >
                  {Object.entries(r.metrics_output)
                    .map(
                      ([k, v]) =>
                        `${k}=${typeof v === "number" ? v.toFixed(4) : v}`,
                    )
                    .join(" · ")}
                </div>
              )}
            </div>
            <StatusBadge status={r.status} />
          </Link>
        ))}
      </Section>

      {frontiers.data && frontiers.data.length > 0 && (
        <Section
          title="Metric frontiers"
          count={frontiers.data.length}
          loading={false}
          empty="No frontiers yet."
        >
          {frontiers.data.map((f: MetricFrontier, i: number) => (
            <div
              key={f.id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                gap: 12,
                padding: "12px 16px",
                borderBottom:
                  i < frontiers.data.length - 1
                    ? "1px solid var(--c-line-soft)"
                    : "none",
                alignItems: "center",
                fontSize: 13,
              }}
            >
              <div>
                <div
                  style={{ display: "flex", gap: 8, alignItems: "baseline" }}
                >
                  <span style={{ fontWeight: 500 }}>
                    {f.primary_metric_name}
                  </span>
                  <span
                    style={{ fontSize: 11.5, color: "var(--c-ink-4)" }}
                  >
                    ({f.primary_metric_direction})
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--c-ink-3)",
                    marginTop: 2,
                  }}
                >
                  Best{" "}
                  <span
                    className="mono"
                    style={{ color: "var(--c-ink-2)" }}
                  >
                    {f.best_metric_value.toFixed(4)}
                  </span>{" "}
                  · {f.successful_runs}/{f.total_runs} runs successful
                </div>
              </div>
              <div style={{ textAlign: "right", fontSize: 12 }}>
                <div
                  style={{
                    color:
                      f.runs_since_improvement >= 5
                        ? "var(--c-err)"
                        : f.runs_since_improvement >= 3
                          ? "var(--c-warn)"
                          : "var(--c-ok)",
                  }}
                >
                  {f.runs_since_improvement === 0
                    ? "Improved last run"
                    : `${f.runs_since_improvement} runs since improvement`}
                </div>
                <Link
                  to="/experiment/$runId"
                  params={{ runId: f.best_run_id }}
                  style={{
                    fontSize: 11.5,
                    color: "var(--c-accent-ink)",
                    textDecoration: "none",
                  }}
                >
                  Best run →
                </Link>
              </div>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  loading,
  empty,
  children,
}: {
  title: string;
  count: number;
  loading: boolean;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 28 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          marginBottom: 10,
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
          {title}
        </h2>
        <span
          style={{
            fontSize: 12,
            color: "var(--c-ink-4)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {count}
        </span>
      </div>
      {loading ? (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>Loading…</div>
      ) : count === 0 ? (
        <div
          className="card"
          style={{
            padding: 20,
            textAlign: "center",
            color: "var(--c-ink-3)",
            fontSize: 13.5,
          }}
        >
          {empty}
        </div>
      ) : (
        <div className="card" style={{ overflow: "hidden" }}>
          {children}
        </div>
      )}
    </section>
  );
}

function Row({
  last,
  primary,
  secondary,
  badge,
}: {
  last: boolean;
  primary: React.ReactNode;
  secondary: React.ReactNode;
  badge: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 12,
        padding: "12px 16px",
        borderBottom: last ? "none" : "1px solid var(--c-line-soft)",
        alignItems: "center",
        fontSize: 13,
      }}
    >
      <div>
        <div style={{ fontWeight: 500 }}>{primary}</div>
        <div
          style={{
            fontSize: 11.5,
            color: "var(--c-ink-3)",
            marginTop: 2,
          }}
        >
          {secondary}
        </div>
      </div>
      {badge}
    </div>
  );
}
