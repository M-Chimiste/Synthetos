import { createFileRoute } from "@tanstack/react-router";
import EventStream from "../components/EventStream";

export const Route = createFileRoute("/events")({
  component: EventsPage,
});

function EventsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Event Stream</h1>
      <p className="mb-4 text-sm text-gray-500">
        Live server-sent events from the backend. Events appear in real time as
        the system processes research tasks.
      </p>
      <EventStream />
    </div>
  );
}
