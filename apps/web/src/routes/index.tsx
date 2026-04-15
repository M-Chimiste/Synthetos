import { createFileRoute, Link } from "@tanstack/react-router";
import { useCharters, useJobs } from "../api/hooks";
import StatusBadge from "../components/StatusBadge";

export const Route = createFileRoute("/")({
  component: DashboardPage,
});

function DashboardPage() {
  const { data, isLoading, error } = useCharters();
  const jobs = useJobs();
  const activeJobs =
    jobs.data?.items.filter((job) =>
      ["pending", "claimed", "running", "paused"].includes(job.status),
    ) ?? [];

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Dashboard</h1>

      {/* Quick stats */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Charters"
          value={data?.total ?? "--"}
          loading={isLoading}
        />
        <StatCard
          label="Active"
          value={
            data?.items.filter((c) => c.status === "active").length ?? "--"
          }
          loading={isLoading}
        />
        <StatCard
          label="Active Jobs"
          value={activeJobs.length}
          loading={jobs.isLoading}
        />
      </div>

      {/* Error state */}
      {error && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load charters: {error.message}
        </div>
      )}

      {/* Recent charters */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Recent Charters</h2>
          <Link
            to="/charters/new"
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
          >
            New Charter
          </Link>
        </div>

        {isLoading && <p className="text-sm text-gray-500">Loading...</p>}

        {data && data.items.length === 0 && (
          <p className="text-sm text-gray-500">
            No charters yet.{" "}
            <Link to="/charters/new" className="text-blue-600 hover:underline">
              Create your first charter
            </Link>{" "}
            to get started.
          </p>
        )}

        {data && data.items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Title</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.slice(0, 10).map((charter) => (
                  <tr key={charter.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link
                        to="/charters/$charterId"
                        params={{ charterId: charter.id }}
                        className="font-medium text-blue-600 hover:underline"
                      >
                        {charter.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={charter.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(charter.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Queue Snapshot</h2>
          <Link to="/events" className="text-sm text-blue-600 hover:underline">
            View live events
          </Link>
        </div>

        {jobs.isLoading && <p className="text-sm text-gray-500">Loading jobs...</p>}

        {jobs.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            Failed to load jobs: {jobs.error.message}
          </div>
        )}

        {jobs.data && jobs.data.items.length === 0 && (
          <p className="text-sm text-gray-500">No jobs queued yet.</p>
        )}

        {jobs.data && jobs.data.items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Priority</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {jobs.data.items.slice(0, 8).map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono">{job.job_type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">{job.priority}</td>
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
    </div>
  );
}

function StatCard({
  label,
  value,
  loading,
}: {
  label: string;
  value: string | number;
  loading: boolean;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">
        {loading ? (
          <span className="inline-block h-7 w-12 animate-pulse rounded bg-gray-200" />
        ) : (
          value
        )}
      </p>
    </div>
  );
}
