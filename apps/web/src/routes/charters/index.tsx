import { createFileRoute, Link } from "@tanstack/react-router";
import { useCharters } from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";

export const Route = createFileRoute("/charters/")({
  component: CharterListPage,
});

function CharterListPage() {
  const { data, isLoading, error } = useCharters();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Charters</h1>
        <Link
          to="/charters/new"
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          New Charter
        </Link>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load charters: {error.message}
        </div>
      )}

      {isLoading && <p className="text-sm text-gray-500">Loading charters...</p>}

      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
          <p className="text-gray-500">No charters yet.</p>
          <Link
            to="/charters/new"
            className="mt-2 inline-block text-sm text-blue-600 hover:underline"
          >
            Create your first charter
          </Link>
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((charter) => (
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
                  <td className="max-w-xs truncate px-4 py-3 text-gray-500">
                    {charter.description}
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
    </div>
  );
}
