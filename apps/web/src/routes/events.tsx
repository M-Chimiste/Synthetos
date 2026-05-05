import { createFileRoute } from "@tanstack/react-router";
import EventStream from "../components/EventStream";

export const Route = createFileRoute("/events")({
  component: EventsPage,
});

function EventsPage() {
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
        Events
      </h1>
      <div
        style={{ color: "var(--c-ink-3)", fontSize: 13.5, marginBottom: 20 }}
      >
        Live stream across all charters.
      </div>
      <div className="card" style={{ padding: "16px 18px" }}>
        <EventStream />
      </div>
    </div>
  );
}
