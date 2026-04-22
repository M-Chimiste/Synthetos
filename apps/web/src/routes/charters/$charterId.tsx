import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import {
  useCharter,
  useCreateCycle,
  useCycles,
  useJobs,
  useResearchState,
} from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";
import StatusDot from "../../components/StatusDot";
import Icon from "../../components/Icon";
import PipelineRail, {
  progressFromCycleStatus,
} from "../../components/PipelineRail";
import EventStream from "../../components/EventStream";
import AutonomyPanel from "../../components/AutonomyPanel";

export const Route = createFileRoute("/charters/$charterId")({
  component: CharterDetailPage,
});

type Tab = "overview" | "cycles" | "jobs" | "events" | "autonomy";

function CharterDetailPage() {
  const { charterId } = Route.useParams();
  const charter = useCharter(charterId);
  const cycles = useCycles(charterId);
  const state = useResearchState(charterId);
  const createCycle = useCreateCycle();
  const activeCycleId = state.data?.active_cycle?.id;
  const jobs = useJobs(activeCycleId, Boolean(activeCycleId));
  const [tab, setTab] = useState<Tab>("overview");

  if (charter.isLoading) {
    return (
      <div style={{ padding: "32px 40px", color: "var(--c-ink-3)" }}>
        Loading charter…
      </div>
    );
  }

  if (charter.error) {
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
          Failed to load charter: {charter.error.message}
        </div>
      </div>
    );
  }

  const c = charter.data;
  if (!c) return null;

  const activeCycle = state.data?.active_cycle;
  const cycleItems = cycles.data?.items ?? [];
  const jobItems = jobs.data?.items ?? [];

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
          to="/charters"
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Charters
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>{c.title}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button type="button" className="btn sm">
            Share
          </button>
          <button type="button" className="btn sm">
            Archive
          </button>
        </div>
      </div>

      <div style={{ padding: "28px 40px", maxWidth: 1240 }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 24,
            marginBottom: 8,
          }}
        >
          <div style={{ flex: 1 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span
                className="mono"
                style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
              >
                {c.id}
              </span>
              <StatusBadge status={c.status} />
              <span style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}>
                Created {new Date(c.created_at).toLocaleDateString()}
              </span>
            </div>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.015em",
                margin: 0,
                lineHeight: 1.3,
              }}
            >
              {c.title}
            </h1>
            {c.description && (
              <p
                style={{
                  color: "var(--c-ink-2)",
                  fontSize: 14.5,
                  marginTop: 8,
                  marginBottom: 0,
                  maxWidth: 720,
                  lineHeight: 1.55,
                }}
              >
                {c.description}
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Link
              to="/charters/$charterId/discovery/new"
              params={{ charterId }}
              className="btn"
            >
              + Start discovery
            </Link>
            <button
              type="button"
              className="btn primary"
              onClick={() => createCycle.mutate(charterId)}
              disabled={createCycle.isPending}
            >
              {createCycle.isPending ? "Creating…" : "+ New cycle"}
            </button>
          </div>
        </div>

        {createCycle.error && (
          <div
            className="card"
            style={{
              padding: 12,
              marginTop: 16,
              borderColor: "var(--c-err)",
              color: "var(--c-err)",
              fontSize: 13,
            }}
          >
            {createCycle.error.message}
          </div>
        )}

        {activeCycle && (
          <div
            className="card"
            style={{
              padding: "20px 24px",
              marginTop: 24,
              background: "var(--c-panel)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                marginBottom: 14,
                flexWrap: "wrap",
              }}
            >
              <span className="section-label">Active cycle</span>
              <span
                className="mono"
                style={{ fontSize: 12, color: "var(--c-ink-2)" }}
              >
                {activeCycle.id}
              </span>
              <StatusBadge status={activeCycle.status} />
              <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
                {activeCycle.started_at
                  ? `started ${new Date(activeCycle.started_at).toLocaleString()}`
                  : `created ${new Date(activeCycle.created_at).toLocaleDateString()}`}
              </span>
              <div
                style={{ marginLeft: "auto", display: "flex", gap: 6 }}
              >
                <button type="button" className="btn sm">
                  <Icon name="pause" size={12} /> Pause loop
                </button>
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => setTab("events")}
                >
                  View timeline
                </button>
              </div>
            </div>
            <PipelineRail progress={progressFromCycleStatus(activeCycle.status)} />
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 0,
                marginTop: 20,
                paddingTop: 16,
                borderTop: "1px solid var(--c-line)",
              }}
            >
              <MiniStat
                label="Cycles"
                value={state.data?.cycles.length ?? 0}
              />
              <MiniStat
                label="Total events"
                value={state.data?.total_events ?? 0}
              />
              <MiniStat
                label="Total jobs"
                value={state.data?.total_jobs ?? 0}
              />
              <MiniStat
                label="Active jobs"
                value={jobItems.length}
                sub={
                  jobItems.length > 0
                    ? `${jobItems.filter((j) => j.status === "running").length} running`
                    : undefined
                }
              />
            </div>
          </div>
        )}

        <div
          style={{
            display: "flex",
            gap: 2,
            marginTop: 28,
            borderBottom: "1px solid var(--c-line)",
          }}
        >
          {(["overview", "cycles", "jobs", "events", "autonomy"] as Tab[]).map(
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
                    tab === t ? "2px solid var(--c-ink)" : "2px solid transparent",
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

        <div style={{ paddingTop: 24 }}>
          {tab === "overview" && (
            <OverviewTab
              problemStatement={c.problem_statement}
              recentEvents={state.data?.recent_events ?? []}
              cycleCount={state.data?.cycles.length ?? 0}
            />
          )}
          {tab === "cycles" && (
            <CyclesTab
              cycles={cycleItems}
              loading={cycles.isLoading}
              onCreate={() => createCycle.mutate(charterId)}
              creating={createCycle.isPending}
            />
          )}
          {tab === "jobs" && (
            <JobsTab
              jobs={jobItems}
              loading={jobs.isLoading}
              activeCycleId={activeCycleId}
            />
          )}
          {tab === "events" && <EventsTab charterId={charterId} />}
          {tab === "autonomy" && (
            <AutonomyTab cycleId={activeCycleId} />
          )}
        </div>
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone?: "ok" | "violet";
}) {
  return (
    <div
      style={{
        padding: "0 16px",
        borderRight: "1px solid var(--c-line-soft)",
      }}
    >
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
          fontSize: 20,
          fontWeight: 600,
          marginTop: 4,
          color:
            tone === "ok"
              ? "var(--c-ok)"
              : tone === "violet"
                ? "var(--c-violet)"
                : "var(--c-ink)",
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.01em",
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{ fontSize: 11.5, color: "var(--c-ink-3)", marginTop: 1 }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function OverviewTab({
  problemStatement,
  recentEvents,
  cycleCount,
}: {
  problemStatement: string;
  recentEvents: Array<{
    id: string;
    event_type: string;
    actor_type: string;
    actor_id: string | null;
    created_at: string;
  }>;
  cycleCount: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1.5fr 1fr",
        gap: 24,
      }}
    >
      <div>
        <div className="card" style={{ padding: 20, marginBottom: 20 }}>
          <div className="section-label" style={{ marginBottom: 8 }}>
            Problem statement
          </div>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.6,
              color: "var(--c-ink-2)",
              margin: 0,
              whiteSpace: "pre-wrap",
            }}
          >
            {problemStatement || "—"}
          </p>
        </div>

        <SectionHeader title="Recent events" />
        <div className="card" style={{ overflow: "hidden" }}>
          {recentEvents.length === 0 && (
            <div
              style={{
                padding: "14px 16px",
                fontSize: 13,
                color: "var(--c-ink-3)",
              }}
            >
              No events yet.
            </div>
          )}
          {recentEvents.slice(0, 8).map((e, i) => (
            <div
              key={e.id}
              style={{
                padding: "10px 16px",
                display: "grid",
                gridTemplateColumns: "72px 1fr 110px",
                gap: 12,
                alignItems: "center",
                fontSize: 12.5,
                borderBottom:
                  i < Math.min(recentEvents.length, 8) - 1
                    ? "1px solid var(--c-line-soft)"
                    : "none",
              }}
            >
              <span
                className="mono"
                style={{ color: "var(--c-ink-4)", fontSize: 11 }}
              >
                {new Date(e.created_at).toLocaleTimeString()}
              </span>
              <span className="mono" style={{ color: "var(--c-ink-2)" }}>
                {e.event_type}
              </span>
              <span style={{ color: "var(--c-ink-3)", fontSize: 11.5 }}>
                {e.actor_id ?? e.actor_type}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionHeader title="Summary" />
        <div className="card" style={{ padding: 20 }}>
          <div style={{ display: "grid", gap: 14 }}>
            <SummaryRow
              label="Cycles"
              value={cycleCount}
              sub={cycleCount > 0 ? "see Cycles tab" : "none yet"}
            />
            <SummaryRow
              label="Recent events"
              value={recentEvents.length}
              sub={recentEvents.length > 0 ? "streaming live" : undefined}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  sub,
}: {
  label: string;
  value: number;
  sub?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
      }}
    >
      <div>
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
        {sub && (
          <div style={{ fontSize: 11.5, color: "var(--c-ink-4)", marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.01em",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function CyclesTab({
  cycles,
  loading,
  onCreate,
  creating,
}: {
  cycles: Array<{
    id: string;
    status: string;
    created_at: string;
  }>;
  loading: boolean;
  onCreate: () => void;
  creating: boolean;
}) {
  return (
    <div>
      <SectionHeader
        title="Cycles"
        count={cycles.length}
        right={
          <button
            type="button"
            className="btn primary"
            onClick={onCreate}
            disabled={creating}
            style={{ fontSize: 12.5, padding: "4px 10px" }}
          >
            {creating ? "Creating…" : "+ New cycle"}
          </button>
        }
      />
      {loading && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Loading cycles…
        </div>
      )}
      {!loading && cycles.length === 0 && (
        <div
          className="card"
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--c-ink-3)",
            fontSize: 13.5,
          }}
        >
          No cycles yet.
        </div>
      )}
      {cycles.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "200px 1fr 120px 140px",
              padding: "10px 16px",
              borderBottom: "1px solid var(--c-line)",
              fontSize: 11,
              color: "var(--c-ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 500,
            }}
          >
            <span>Cycle</span>
            <span>Pipeline</span>
            <span>Status</span>
            <span>Created</span>
          </div>
          {cycles.map((cy, i) => (
            <div
              key={cy.id}
              style={{
                display: "grid",
                gridTemplateColumns: "200px 1fr 120px 140px",
                padding: "12px 16px",
                borderBottom:
                  i < cycles.length - 1 ? "1px solid var(--c-line-soft)" : "none",
                alignItems: "center",
                fontSize: 13.5,
              }}
            >
              <span className="mono" style={{ color: "var(--c-ink-2)" }}>
                {cy.id}
              </span>
              <PipelineRail
                progress={progressFromCycleStatus(cy.status)}
                showLabels={false}
                compact
              />
              <StatusBadge status={cy.status} />
              <span style={{ color: "var(--c-ink-3)", fontSize: 12 }}>
                {new Date(cy.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function JobsTab({
  jobs,
  loading,
  activeCycleId,
}: {
  jobs: Array<{
    id: string;
    job_type: string;
    status: string;
    claimed_by: string | null;
    priority: number;
    created_at: string;
  }>;
  loading: boolean;
  activeCycleId: string | undefined;
}) {
  if (!activeCycleId) {
    return (
      <div
        className="card"
        style={{
          padding: 20,
          fontSize: 13.5,
          color: "var(--c-ink-3)",
        }}
      >
        Create a cycle to start queueing jobs.
      </div>
    );
  }
  if (loading) {
    return (
      <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
        Loading jobs…
      </div>
    );
  }
  if (jobs.length === 0) {
    return (
      <div
        className="card"
        style={{
          padding: 20,
          fontSize: 13.5,
          color: "var(--c-ink-3)",
        }}
      >
        No jobs for the active cycle.
      </div>
    );
  }
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "28px 1fr 140px 140px 140px",
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
        <span>Type</span>
        <span>Status</span>
        <span>Worker</span>
        <span>Created</span>
      </div>
      {jobs.map((j, i) => (
        <div
          key={j.id}
          style={{
            display: "grid",
            gridTemplateColumns: "28px 1fr 140px 140px 140px",
            padding: "10px 16px",
            borderBottom:
              i < jobs.length - 1 ? "1px solid var(--c-line-soft)" : "none",
            alignItems: "center",
            fontSize: 13,
          }}
        >
          <StatusDot status={j.status} pulse={j.status === "running"} />
          <span className="mono" style={{ color: "var(--c-ink-2)" }}>
            {j.job_type}
          </span>
          <StatusBadge status={j.status} />
          <span style={{ color: "var(--c-ink-3)", fontSize: 12 }}>
            {j.claimed_by ?? "unclaimed"}
          </span>
          <span style={{ color: "var(--c-ink-3)", fontSize: 12 }}>
            {new Date(j.created_at).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

function EventsTab({ charterId }: { charterId: string }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "14px 16px" }}>
        <EventStream charterId={charterId} />
      </div>
    </div>
  );
}

function AutonomyTab({ cycleId }: { cycleId: string | undefined }) {
  if (!cycleId) {
    return (
      <div
        className="card"
        style={{
          padding: 20,
          fontSize: 13.5,
          color: "var(--c-ink-3)",
        }}
      >
        No active cycle. Autonomy configuration becomes available once a cycle
        is running.
      </div>
    );
  }
  return (
    <div className="card" style={{ padding: 20 }}>
      <AutonomyPanel cycleId={cycleId} />
    </div>
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
