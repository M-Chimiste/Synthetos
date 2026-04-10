import { createFileRoute } from "@tanstack/react-router";
import { useSkills, useDiscoverSkills } from "../api/hooks";
import StatusBadge from "../components/StatusBadge";

export const Route = createFileRoute("/skills")({
  component: SkillsPage,
});

function SkillsPage() {
  const { data, isLoading, error } = useSkills();
  const discover = useDiscoverSkills();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Skills</h1>
        <button
          onClick={() => discover.mutate()}
          disabled={discover.isPending}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {discover.isPending ? "Discovering..." : "Discover Skills"}
        </button>
      </div>

      {discover.isSuccess && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          Discovered {discover.data.discovered} new skill(s).
        </div>
      )}

      {discover.error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Discovery failed: {discover.error.message}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load skills: {error.message}
        </div>
      )}

      {isLoading && <p className="text-sm text-gray-500">Loading skills...</p>}

      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
          <p className="text-gray-500">No skills registered yet.</p>
          <p className="mt-1 text-sm text-gray-400">
            Click "Discover Skills" to scan for available skill packages.
          </p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((skill) => (
            <div
              key={skill.id}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="mb-2 flex items-start justify-between">
                <h3 className="font-medium">{skill.name}</h3>
                <StatusBadge status={skill.enabled ? "active" : "disabled"} />
              </div>
              <p className="mb-3 text-sm text-gray-500">{skill.description}</p>
              <p className="text-xs text-gray-400">Phase: {skill.phase}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
