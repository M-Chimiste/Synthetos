import { createFileRoute, Link } from "@tanstack/react-router";
import {
  useCharter,
  useCreateCycle,
  useCycles,
  useJobs,
  useResearchState,
} from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";
import EventStream from "../../components/EventStream";

export const Route = createFileRoute("/charters/$charterId")({
  component: CharterDetailPage,
});

function CharterDetailPage() {
  const { charterId } = Route.useParams();
  const charter = useCharter(charterId);
  const cycles = useCycles(charterId);
  const state = useResearchState(charterId);
  const createCycle = useCreateCycle();
  const activeCycleId = state.data?.active_cycle?.id;
  const jobs = useJobs(activeCycleId, Boolean(activeCycleId));

  if (charter.isLoading) {
    return <p className="text-sm text-gray-500">Loading charter...</p>;
  }

  if (charter.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load charter: {charter.error.message}
      </div>
    );
  }

  const c = charter.data;
  if (!c) return null;

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link to="/charters" className="text-sm text-gray-500 hover:text-gray-700">
          &larr; Charters
        </Link>
        <div className="mt-2 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold">{c.title}</h1>
            <p className="mt-1 text-gray-500">{c.description}</p>
          </div>
          <StatusBadge status={c.status} />
        </div>
      </div>

      {/* Problem statement */}
      <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-medium uppercase text-gray-500">
          Problem Statement
        </h2>
        <p className="whitespace-pre-wrap text-sm text-gray-800">
          {c.problem_statement}
        </p>
      </section>

      {/* State snapshot */}
      {state.data && (
        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <MiniStat label="Cycles" value={state.data.cycles.length} />
          <MiniStat label="Events" value={state.data.total_events} />
          <MiniStat label="Jobs" value={state.data.total_jobs} />
        </section>
      )}

      {state.data?.active_cycle && (
        <section className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium uppercase text-gray-500">
                Active Cycle
              </h2>
              <p className="mt-1 font-mono text-sm text-gray-800">
                {state.data.active_cycle.id}
              </p>
            </div>
            <StatusBadge status={state.data.active_cycle.status} />
          </div>
        </section>
      )}

      {/* Cycles */}
      <section className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Cycles</h2>
          <button
            onClick={() => createCycle.mutate(charterId)}
            disabled={createCycle.isPending}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {createCycle.isPending ? "Creating..." : "New Cycle"}
          </button>
        </div>

        {createCycle.error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {createCycle.error.message}
          </div>
        )}

        {cycles.isLoading && (
          <p className="text-sm text-gray-500">Loading cycles...</p>
        )}

        {cycles.data && cycles.data.items.length === 0 && (
          <p className="text-sm text-gray-500">No cycles yet.</p>
        )}

        {cycles.data && cycles.data.items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Cycle</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {cycles.data.items.map((cycle) => (
                  <tr key={cycle.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono">
                      {cycle.id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={cycle.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(cycle.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-medium">Active Jobs</h2>

        {!activeCycleId && (
          <p className="text-sm text-gray-500">Create a cycle to start queueing jobs.</p>
        )}

        {jobs.isLoading && (
          <p className="text-sm text-gray-500">Loading jobs...</p>
        )}

        {jobs.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            Failed to load jobs: {jobs.error.message}
          </div>
        )}

        {activeCycleId && jobs.data && jobs.data.items.length === 0 && (
          <p className="text-sm text-gray-500">No jobs for the active cycle.</p>
        )}

        {activeCycleId && jobs.data && jobs.data.items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Worker</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {jobs.data.items.map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono">{job.job_type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {job.claimed_by ?? "unclaimed"}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {state.data && state.data.recent_events.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-3 text-lg font-medium">Recent Events</h2>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {state.data.recent_events.slice(0, 8).map((event) => (
                  <tr key={event.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono">{event.event_type}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {event.actor_id ?? event.actor_type}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(event.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Event stream */}
      <section>
        <h2 className="mb-3 text-lg font-medium">Live Events</h2>
        <EventStream charterId={charterId} />
      </section>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
