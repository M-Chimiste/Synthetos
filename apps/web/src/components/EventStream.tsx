import type { DomainEvent } from "../api/client";
import { useEffect, useRef, useState } from "react";

interface SSEEvent {
  id: string;
  eventType: string;
  payload: string;
  timestamp: string;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export default function EventStream({
  charterId,
}: {
  charterId?: string;
}) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const lastEventIdRef = useRef<string | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let url = `${BASE_URL}/events/stream`;
    const params = new URLSearchParams();
    if (charterId) params.set("charter_id", charterId);
    if (lastEventIdRef.current)
      params.set("last_event_id", lastEventIdRef.current);
    const qs = params.toString();
    if (qs) url += `?${qs}`;

    const source = new EventSource(url);

    source.onopen = () => setConnected(true);

    source.onmessage = (e) => {
      let raw: DomainEvent;
      try {
        raw = JSON.parse(e.data) as DomainEvent;
      } catch {
        return;
      }
      const parsed: SSEEvent = {
        id: raw.id || e.lastEventId || crypto.randomUUID(),
        eventType: raw.event_type,
        payload: raw.payload ? JSON.stringify(raw.payload) : "{}",
        timestamp: raw.created_at ?? new Date().toISOString(),
      };
      lastEventIdRef.current = parsed.id;
      setEvents((prev) => [...prev.slice(-199), parsed]);
    };

    source.onerror = () => {
      setConnected(false);
    };

    return () => {
      source.close();
      setConnected(false);
    };
  }, [charterId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-sm">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            connected ? "bg-green-500" : "bg-red-400"
          }`}
        />
        <span className="text-gray-500">
          {connected ? "Connected" : "Disconnected"}
        </span>
        <span className="text-gray-400">
          ({events.length} event{events.length !== 1 ? "s" : ""})
        </span>
      </div>
      <div className="max-h-96 overflow-y-auto rounded-lg border border-gray-200 bg-gray-900 p-4 font-mono text-xs text-gray-100">
        {events.length === 0 && (
          <p className="text-gray-500">Waiting for events...</p>
        )}
        {events.map((evt) => (
          <div key={evt.id} className="mb-1">
            <span className="text-gray-500">
              {new Date(evt.timestamp).toLocaleTimeString()}
            </span>{" "}
            <span className="text-cyan-400">[{evt.eventType}]</span>{" "}
            <span className="text-gray-300">{evt.payload}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
