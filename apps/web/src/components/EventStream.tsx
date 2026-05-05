import type { DomainEvent } from "../api/client";
import { useEffect, useRef, useState } from "react";

interface SSEEvent {
  id: string;
  eventType: string;
  payload: string;
  timestamp: string;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export default function EventStream({ charterId }: { charterId?: string }) {
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 12,
          marginBottom: 10,
        }}
      >
        <span className={`dot ${connected ? "ok pulse" : "err"}`} />
        <span style={{ color: "var(--c-ink-2)" }}>
          {connected ? "Live" : "Disconnected"}
        </span>
        <span style={{ color: "var(--c-ink-4)" }}>
          · {events.length} event{events.length === 1 ? "" : "s"}
          {charterId ? " · filtered by charter" : ""}
        </span>
      </div>
      <div
        style={{
          maxHeight: 420,
          overflowY: "auto",
          borderRadius: "var(--r-md)",
          border: "1px solid var(--c-line-soft)",
          background: "var(--c-panel)",
        }}
      >
        {events.length === 0 && (
          <div
            style={{
              padding: "14px 14px",
              fontSize: 12.5,
              color: "var(--c-ink-4)",
            }}
          >
            Waiting for events…
          </div>
        )}
        {events.map((evt, i) => (
          <div
            key={evt.id}
            style={{
              display: "grid",
              gridTemplateColumns: "90px 1fr",
              gap: 10,
              padding: "6px 14px",
              borderBottom:
                i < events.length - 1
                  ? "1px solid var(--c-line-soft)"
                  : "none",
              fontSize: 12,
              fontFamily: "var(--f-mono)",
            }}
          >
            <span style={{ color: "var(--c-ink-4)" }}>
              {new Date(evt.timestamp).toLocaleTimeString()}
            </span>
            <div>
              <span style={{ color: "var(--c-accent-ink)" }}>
                [{evt.eventType}]
              </span>{" "}
              <span style={{ color: "var(--c-ink-2)" }}>{evt.payload}</span>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
