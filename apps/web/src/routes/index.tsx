import type { CSSProperties, ReactNode } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useCharters, useCycles, useJobs } from "../api/hooks";
import type { Charter, Cycle } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import StatusDot from "../components/StatusDot";
import PipelineRail, {
  progressFromCycleStatus,
} from "../components/PipelineRail";
import Sparkline from "../components/Sparkline";

export const Route = createFileRoute("/")({
  component: DashboardPage,
});

const ACTIVE_CHARTER_STATUSES = new Set([
  "active",
  "experimenting",
  "analyzing",
  "discovering",
  "planning",
]);

function greetingForHour(h: number): string {
  if (h < 5) return "Working late.";
  if (h < 12) return "Good morning.";
  if (h < 18) return "Good afternoon.";
  return "Good evening.";
}

function formatDateHeader(d: Date): string {
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

function DashboardPage() {
  const charters = useCharters();
  const jobs = useJobs();

  const now = new Date();
  const greeting = greetingForHour(now.getHours());
  const todayStart = new Date(now);
  todayStart.setHours(0, 0, 0, 0);

  const charterItems = charters.data?.items ?? [];
  const jobItems = jobs.data?.items ?? [];

  const activeCharters = charterItems.filter((c) =>
    ACTIVE_CHARTER_STATUSES.has(c.status),
  );
  const todaysJobs = jobItems.filter(
    (j) => new Date(j.created_at) >= todayStart,
  );
  const runningJobs = jobItems.filter((j) => j.status === "running");
  const succeededToday = todaysJobs.filter((j) => j.status === "succeeded");
  const failedToday = todaysJobs.filter((j) => j.status === "failed");

  // Sparkline: jobs created per hour over the last 12 hours.
  // "Running now" is a point-in-time count; no timeseries available without
  // backend history, so only "Jobs today" gets a sparkline.
  const jobsByHour = bucketByHour(todaysJobs, now, 12);

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div style={{ marginBottom: 32 }}>
        <div className="section-label" style={{ marginBottom: 4 }}>
          {formatDateHeader(now)}
        </div>
        <h1
          style={{
            fontSize: 24,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            margin: 0,
          }}
        >
          {greeting}
        </h1>
        <div
          style={{ color: "var(--c-ink-3)", marginTop: 4, fontSize: 14 }}
        >
          {activeCharters.length} charter
          {activeCharters.length === 1 ? "" : "s"} active ·{" "}
          {todaysJobs.length} job{todaysJobs.length === 1 ? "" : "s"} today
          {runningJobs.length > 0 ? ` · ${runningJobs.length} running now` : ""}
        </div>
      </div>

      {charters.error && (
        <div
          className="card"
          style={{
            padding: 14,
            marginBottom: 24,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          Failed to load charters: {charters.error.message}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          marginBottom: 32,
        }}
      >
        <StatCard
          label="Charters"
          value={
            charters.isLoading ? "—" : String(charters.data?.total ?? "—")
          }
          delta={`${activeCharters.length} active`}
        />
        <StatCard
          label="Jobs today"
          value={jobs.isLoading ? "—" : String(todaysJobs.length)}
          delta={`${succeededToday.length} succeeded · ${failedToday.length} failed`}
          spark={jobsByHour}
        />
        <StatCard
          label="Running now"
          value={jobs.isLoading ? "—" : String(runningJobs.length)}
          delta={`of ${jobItems.length} in queue`}
          color="var(--c-ok)"
        />
        <StatCard
          label="Queue size"
          value={jobs.isLoading ? "—" : String(jobItems.length)}
          delta="all statuses"
        />
      </div>

      <section style={{ marginBottom: 32 }}>
        <SectionHeader
          title="Active cycles"
          count={activeCharters.length}
          right={
            <Link
              to="/charters/new"
              className="btn primary"
              style={{ fontSize: 12.5, padding: "4px 10px" }}
            >
              + New charter
            </Link>
          }
        />
        {charters.isLoading && <LoadingRow label="Loading charters…" />}
        {!charters.isLoading && activeCharters.length === 0 && (
          <EmptyRow>
            No active cycles.{" "}
            <Link
              to="/charters/new"
              style={{ color: "var(--c-accent-ink)" }}
            >
              Start a new charter →
            </Link>
          </EmptyRow>
        )}
        {activeCharters.length > 0 && (
          <div className="card" style={{ overflow: "hidden" }}>
            {activeCharters.map((c, i) => (
              <ActiveCycleRow
                key={c.id}
                charter={c}
                last={i === activeCharters.length - 1}
              />
            ))}
          </div>
        )}
      </section>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.3fr 1fr",
          gap: 24,
        }}
      >
        <section>
          <SectionHeader
            title="Recent jobs"
            right={
              <Link
                to="/events"
                style={{ fontSize: 12.5, color: "var(--c-ink-3)" }}
              >
                Live events →
              </Link>
            }
          />
          <div className="card" style={{ overflow: "hidden" }}>
            {jobs.isLoading && <LoadingRow label="Loading jobs…" />}
            {!jobs.isLoading && jobItems.length === 0 && (
              <EmptyRow>No jobs queued yet.</EmptyRow>
            )}
            {jobItems.slice(0, 6).map((j, i) => (
              <div
                key={j.id}
                style={{
                  padding: "10px 14px",
                  display: "grid",
                  gridTemplateColumns: "28px 1fr auto",
                  gap: 12,
                  alignItems: "center",
                  borderBottom:
                    i < Math.min(jobItems.length, 6) - 1
                      ? "1px solid var(--c-line-soft)"
                      : "none",
                  fontSize: 13,
                }}
              >
                <StatusDot
                  status={j.status}
                  pulse={j.status === "running"}
                />
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <span
                      className="mono"
                      style={{ color: "var(--c-ink-2)", fontSize: 12.5 }}
                    >
                      {j.job_type}
                    </span>
                    <StatusBadge status={j.status} />
                  </div>
                  <div
                    style={{
                      fontSize: 11.5,
                      color: "var(--c-ink-4)",
                      marginTop: 2,
                    }}
                  >
                    {j.claimed_by ?? "unclaimed"} · priority {j.priority} ·{" "}
                    {new Date(j.created_at).toLocaleTimeString()}
                  </div>
                </div>
                <span
                  className="mono"
                  style={{ fontSize: 11, color: "var(--c-ink-4)" }}
                >
                  {j.id.slice(0, 8)}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <SectionHeader title="Recent charters" />
          <div className="card" style={{ overflow: "hidden" }}>
            {charterItems.slice(0, 6).map((c, i) => (
              <Link
                key={c.id}
                to="/charters/$charterId"
                params={{ charterId: c.id }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 14px",
                  borderBottom:
                    i < Math.min(charterItems.length, 6) - 1
                      ? "1px solid var(--c-line-soft)"
                      : "none",
                  textDecoration: "none",
                  color: "inherit",
                }}
              >
                <StatusDot status={c.status} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: 13,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {c.title}
                  </div>
                  <div
                    className="mono"
                    style={{
                      fontSize: 11,
                      color: "var(--c-ink-4)",
                      marginTop: 2,
                    }}
                  >
                    {c.id.slice(0, 12)}
                  </div>
                </div>
                <StatusBadge status={c.status} />
              </Link>
            ))}
            {!charters.isLoading && charterItems.length === 0 && (
              <EmptyRow>No charters yet.</EmptyRow>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ActiveCycleRow({
  charter,
  last,
}: {
  charter: Charter;
  last: boolean;
}) {
  const cyclesQuery = useCycles(charter.id);
  const latest: Cycle | undefined = cyclesQuery.data?.items[0];

  return (
    <Link
      to="/charters/$charterId"
      params={{ charterId: charter.id }}
      style={{
        padding: "18px 20px",
        borderBottom: last ? "none" : "1px solid var(--c-line-soft)",
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 16,
        alignItems: "center",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 4,
          }}
        >
          <span className="mono" style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}>
            {charter.id.slice(0, 12)}
          </span>
          <StatusBadge status={charter.status} />
        </div>
        <div style={{ fontSize: 14.5, fontWeight: 500, marginBottom: 8 }}>
          {charter.title}
        </div>
        <div
          style={{ display: "flex", alignItems: "center", gap: 16 }}
        >
          {latest ? (
            <>
              <PipelineRail
                progress={progressFromCycleStatus(latest.status)}
                showLabels={false}
                compact
              />
              <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                Cycle <span className="mono">{latest.id.slice(0, 8)}</span> ·{" "}
                <span style={{ textTransform: "capitalize" }}>
                  {latest.status.replace(/_/g, " ")}
                </span>
              </span>
            </>
          ) : (
            <span style={{ fontSize: 12, color: "var(--c-ink-4)" }}>
              {cyclesQuery.isLoading ? "Loading cycle…" : "No cycle yet"}
            </span>
          )}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11.5, color: "var(--c-ink-4)" }}>
          Created {new Date(charter.created_at).toLocaleDateString()}
        </div>
      </div>
    </Link>
  );
}

function SectionHeader({
  title,
  count,
  right,
}: {
  title: string;
  count?: number;
  right?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        marginBottom: 10,
        gap: 8,
      }}
    >
      <h2
        style={{
          fontSize: 13,
          fontWeight: 600,
          margin: 0,
          letterSpacing: "-0.005em",
        }}
      >
        {title}
      </h2>
      {count != null && (
        <span
          style={{
            fontSize: 12,
            color: "var(--c-ink-4)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {count}
        </span>
      )}
      <div style={{ marginLeft: "auto" }}>{right}</div>
    </div>
  );
}

function StatCard({
  label,
  value,
  delta,
  color = "var(--c-accent)",
  spark,
}: {
  label: string;
  value: string;
  delta?: string;
  color?: string;
  spark?: number[];
}) {
  const showSpark =
    spark && spark.length >= 2 && spark.some((v) => v > 0);
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div
        style={{ fontSize: 11.5, color: "var(--c-ink-3)", fontWeight: 500 }}
      >
        {label}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginTop: 6,
          minHeight: 26,
        }}
      >
        <div
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.015em",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {value}
        </div>
        {showSpark && (
          <Sparkline values={spark} color={color} width={62} height={18} />
        )}
      </div>
      {delta && (
        <div
          style={{ fontSize: 11.5, color: "var(--c-ink-3)", marginTop: 4 }}
        >
          {delta}
        </div>
      )}
    </div>
  );
}

/**
 * Bucket items with a `created_at` timestamp into `bucketCount` consecutive
 * hourly slots ending at `endTime`'s hour. Used for the dashboard sparklines.
 */
function bucketByHour(
  items: { created_at: string }[],
  endTime: Date,
  bucketCount: number,
): number[] {
  const buckets = Array(bucketCount).fill(0) as number[];
  const endHour = new Date(endTime);
  endHour.setMinutes(0, 0, 0);
  const cutoff = endHour.getTime() - (bucketCount - 1) * 3_600_000;
  for (const it of items) {
    const t = new Date(it.created_at).getTime();
    if (t < cutoff) continue;
    const idx = Math.floor((t - cutoff) / 3_600_000);
    if (idx >= 0 && idx < bucketCount) buckets[idx]++;
  }
  return buckets;
}

function LoadingRow({ label }: { label: string }) {
  return (
    <div
      style={{
        padding: "16px 18px",
        fontSize: 13,
        color: "var(--c-ink-3)",
      }}
    >
      {label}
    </div>
  );
}

function EmptyRow({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        padding: "16px 18px",
        fontSize: 13,
        color: "var(--c-ink-3)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
