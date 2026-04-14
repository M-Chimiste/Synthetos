import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import type { DomainEvent } from "../../../api/client";

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

const PHASE_GROUPS: Array<{ prefix: string; label: string; tone: string }> = [
  { prefix: "discovery.", label: "Discovery", tone: "bg-blue-100 text-blue-800" },
  { prefix: "analysis.", label: "Analysis", tone: "bg-purple-100 text-purple-800" },
  { prefix: "ideation.", label: "Ideation", tone: "bg-pink-100 text-pink-800" },
  { prefix: "protocol.", label: "Protocol", tone: "bg-indigo-100 text-indigo-800" },
  { prefix: "execution.", label: "Execution", tone: "bg-amber-100 text-amber-800" },
  { prefix: "verification.", label: "Verification", tone: "bg-emerald-100 text-emerald-800" },
  { prefix: "remediation.", label: "Remediation", tone: "bg-orange-100 text-orange-800" },
  { prefix: "signal.", label: "Signal/Frontier", tone: "bg-teal-100 text-teal-800" },
  { prefix: "autonomy.", label: "Autonomy loop", tone: "bg-sky-100 text-sky-800" },
  { prefix: "pattern.", label: "Patterns", tone: "bg-yellow-100 text-yellow-800" },
  { prefix: "skill.", label: "Skills", tone: "bg-gray-200 text-gray-700" },
  { prefix: "job.", label: "Job lifecycle", tone: "bg-rose-100 text-rose-800" },
  { prefix: "pilot.", label: "Pilot", tone: "bg-lime-100 text-lime-800" },
];

function groupFor(eventType: string): { label: string; tone: string } {
  for (const g of PHASE_GROUPS) {
    if (eventType.startsWith(g.prefix)) return g;
  }
  return { label: "Other", tone: "bg-gray-100 text-gray-700" };
}

function TimelinePage() {
  const { cycleId } = Route.useParams();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState<string>("");
  const lastEventIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const url = `${BASE_URL}/events/stream`;
    // The stream filters by charter_id only; the client filters cycle_id below.
    const source = new EventSource(url);
    source.onopen = () => setConnected(true);
    source.onmessage = (e) => {
      let raw: DomainEvent;
      try {
        raw = JSON.parse(e.data) as DomainEvent;
      } catch {
        return;
      }
      if (raw.cycle_id !== cycleId) return;
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

  const visible = filter
    ? events.filter((e) => e.group === filter)
    : events;

  return (
    <div>
      <h1 className="text-2xl font-semibold">Cycle timeline</h1>
      <p className="mt-1 font-mono text-xs text-gray-500">{cycleId}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            connected ? "bg-green-500" : "bg-red-400"
          }`}
        />
        <span className="text-sm text-gray-500">
          {connected ? "Streaming" : "Disconnected"}
        </span>
        <span className="text-xs text-gray-400">
          {events.length} event{events.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => setFilter("")}
          className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
            filter === "" ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-600"
          }`}
        >
          all
        </button>
        {PHASE_GROUPS.map((g) => (
          <button
            key={g.label}
            onClick={() => setFilter(g.label)}
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              filter === g.label ? "ring-2 ring-gray-900" : ""
            } ${g.tone}`}
          >
            {g.label}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-gray-200 bg-white">
        {visible.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">
            Waiting for events for this cycle…
          </p>
        ) : (
          <ol className="divide-y divide-gray-100">
            {visible.map((evt) => {
              const grouping = groupFor(evt.eventType);
              return (
                <li key={evt.id} className="flex items-start gap-3 px-3 py-2">
                  <span className="w-28 shrink-0 font-mono text-xs text-gray-500">
                    {new Date(evt.createdAt).toLocaleTimeString()}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${grouping.tone}`}
                  >
                    {grouping.label}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-gray-900">
                      {evt.eventType}
                    </p>
                    {evt.payload && Object.keys(evt.payload).length > 0 && (
                      <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2 text-xs text-gray-700">
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
