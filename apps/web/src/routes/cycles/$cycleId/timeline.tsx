import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetchCycleIntrospection, type DomainEvent } from "../../../api/client";
import StatusBadge from "../../../components/StatusBadge";

export const Route = createFileRoute("/cycles/$cycleId/timeline")({
  component: TimelinePage,
});

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

interface TimelineEvent {
  id: string;
  eventType: string;
  payload: Record<string, unknown> | null;
  cycleId: string | null;
  createdAt: string;
  group: string;
}

const PHASE_GROUPS: Array<{
  prefix: string;
  label: string;
  tone: "ok" | "warn" | "err" | "violet" | "accent" | "slate";
}> = [
  { prefix: "discovery.", label: "Discovery", tone: "violet" },
  { prefix: "analysis.", label: "Analysis", tone: "violet" },
  { prefix: "ideation.", label: "Ideation", tone: "violet" },
  { prefix: "protocol.", label: "Protocol", tone: "accent" },
  { prefix: "execution.", label: "Execution", tone: "accent" },
  { prefix: "verification.", label: "Verification", tone: "ok" },
  { prefix: "remediation.", label: "Remediation", tone: "warn" },
  { prefix: "signal.", label: "Signal", tone: "ok" },
  { prefix: "autonomy.", label: "Autonomy", tone: "violet" },
  { prefix: "goal.", label: "Goals", tone: "accent" },
  { prefix: "result.", label: "Results", tone: "ok" },
  { prefix: "pattern.", label: "Patterns", tone: "warn" },
  { prefix: "skill.", label: "Skills", tone: "slate" },
  { prefix: "job.", label: "Jobs", tone: "slate" },
  { prefix: "pilot.", label: "Pilot", tone: "ok" },
];

function groupFor(eventType: string): { label: string; tone: string } {
  for (const g of PHASE_GROUPS) {
    if (eventType.startsWith(g.prefix)) return g;
  }
  return { label: "Other", tone: "slate" };
}

function TimelinePage() {
  const { cycleId } = Route.useParams();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState<string>("");
  const lastEventIdRef = useRef<string | undefined>(undefined);
  const introspection = useQuery({
    queryKey: ["cycles", cycleId, "introspection"],
    queryFn: () => fetchCycleIntrospection(cycleId),
    retry: false,
    refetchInterval: 10_000,
  });

  useEffect(() => {
    const params = new URLSearchParams({ cycle_id: cycleId });
    const url = `${BASE_URL}/events/stream?${params.toString()}`;
    const source = new EventSource(url);
    source.onopen = () => setConnected(true);
    source.onmessage = (e) => {
      let raw: DomainEvent;
      try {
        raw = JSON.parse(e.data) as DomainEvent;
      } catch {
        return;
      }
      const id = raw.id || e.lastEventId || crypto.randomUUID();
      const grouping = groupFor(raw.event_type);
      lastEventIdRef.current = id;
      setEvents((prev) => [
        ...prev.slice(-499),
        {
          id,
          eventType: raw.event_type,
          payload: raw.payload ?? null,
          cycleId: raw.cycle_id,
          createdAt: raw.created_at ?? new Date().toISOString(),
          group: grouping.label,
        },
      ]);
    };
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
    };
  }, [cycleId]);

  const visible = filter ? events.filter((e) => e.group === filter) : events;

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <h1
        style={{
          fontSize: 22,
          fontWeight: 600,
          letterSpacing: "-0.015em",
          margin: 0,
          marginBottom: 4,
        }}
      >
        Cycle timeline
      </h1>
      <div
        className="mono"
        style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
      >
        {cycleId}
      </div>

      {introspection.data && (
        <div className="card" style={{ marginTop: 16, padding: 16 }}>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: 8,
            }}
          >
            <div className="section-label">Result introspection</div>
            <StatusBadge status={introspection.data.publication_readiness} />
            <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
              {introspection.data.runs.length} runs ·{" "}
              {introspection.data.model_artifacts.length} model artifacts
            </span>
          </div>
          <div style={{ fontSize: 13, color: "var(--c-ink-2)", lineHeight: 1.55 }}>
            {introspection.data.interpretation}
          </div>
          {Object.keys(introspection.data.metrics).length > 0 && (
            <div
              style={{
                marginTop: 10,
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                fontSize: 12,
              }}
            >
              {Object.entries(introspection.data.metrics)
                .slice(0, 6)
                .map(([name, values]) => (
                  <span
                    key={name}
                    className="mono"
                    style={{
                      color: "var(--c-accent-ink)",
                      background: "var(--c-panel)",
                      padding: "3px 6px",
                      borderRadius: 4,
                    }}
                  >
                    {name}={values.map(formatValue).join(", ")}
                  </span>
                ))}
            </div>
          )}
          {introspection.data.model_artifacts.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {introspection.data.model_artifacts.slice(0, 6).map((artifact) => (
                <a
                  key={`${artifact.run_id}-${artifact.artifact_id}`}
                  href={artifact.download_url}
                  style={{ color: "var(--c-accent-ink)", fontSize: 12.5 }}
                >
                  {artifact.name}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      <div
        style={{
          marginTop: 16,
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <span className={`dot ${connected ? "ok pulse" : "err"}`} />
        <span style={{ fontSize: 12, color: "var(--c-ink-2)" }}>
          {connected ? "Streaming" : "Disconnected"}
        </span>
        <span style={{ fontSize: 11.5, color: "var(--c-ink-4)" }}>
          · {events.length} event{events.length === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={() => setFilter("")}
          className="btn sm"
          style={{
            background: filter === "" ? "var(--c-ink)" : "var(--c-bg-elev)",
            color: filter === "" ? "var(--c-bg)" : "var(--c-ink-2)",
            borderColor: filter === "" ? "var(--c-ink)" : "var(--c-line)",
            marginLeft: 8,
          }}
        >
          All
        </button>
        {PHASE_GROUPS.map((g) => (
          <button
            key={g.label}
            type="button"
            onClick={() => setFilter(g.label)}
            className={`chip ${g.tone}`}
            style={{
              cursor: "pointer",
              borderWidth: filter === g.label ? 2 : 1,
              borderStyle: "solid",
              borderColor:
                filter === g.label ? "var(--c-ink)" : "transparent",
            }}
          >
            {g.label}
          </button>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16, overflow: "hidden" }}>
        {visible.length === 0 ? (
          <div
            style={{
              padding: 16,
              fontSize: 13,
              color: "var(--c-ink-3)",
            }}
          >
            Waiting for events for this cycle…
          </div>
        ) : (
          <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {visible.map((evt, i) => {
              const grouping = groupFor(evt.eventType);
              return (
                <li
                  key={evt.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "100px max-content 1fr",
                    gap: 12,
                    padding: "10px 14px",
                    borderBottom:
                      i < visible.length - 1
                        ? "1px solid var(--c-line-soft)"
                        : "none",
                    alignItems: "start",
                  }}
                >
                  <span
                    className="mono"
                    style={{
                      fontSize: 11,
                      color: "var(--c-ink-4)",
                    }}
                  >
                    {new Date(evt.createdAt).toLocaleTimeString()}
                  </span>
                  <span
                    className={`chip ${grouping.tone}`}
                    style={{ fontSize: 10.5 }}
                  >
                    {grouping.label}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div
                      className="mono"
                      style={{
                        fontSize: 12.5,
                        color: "var(--c-ink)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {evt.eventType}
                    </div>
                    {evt.payload && Object.keys(evt.payload).length > 0 && (
                      <pre
                        style={{
                          marginTop: 4,
                          marginBottom: 0,
                          padding: 8,
                          background: "var(--c-panel)",
                          borderRadius: "var(--r-sm)",
                          fontSize: 11.5,
                          color: "var(--c-ink-2)",
                          fontFamily: "var(--f-mono)",
                          whiteSpace: "pre-wrap",
                          maxHeight: 240,
                          overflow: "auto",
                        }}
                      >
                        {JSON.stringify(evt.payload, null, 2)}
                      </pre>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  return typeof value === "number" ? value.toFixed(4) : String(value);
}
