import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { fetchAnalysisSessions } from "../../api/analysis";
import StatusBadge from "../../components/StatusBadge";

export const Route = createFileRoute("/analysis/")({
  component: AnalysisIndex,
});

function AnalysisIndex() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analysis-sessions"],
    queryFn: () => fetchAnalysisSessions({ limit: 50 }),
  });

  if (isLoading) return <div className="p-4">Loading analysis sessions...</div>;
  if (error) return <div className="p-4 text-red-500">Error loading sessions</div>;

  const sessions = data?.items ?? [];

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-2xl font-bold">Paper Analysis</h1>
      <p className="text-sm text-gray-500">
        {data?.total ?? 0} analysis session(s)
      </p>

      <div className="space-y-2">
        {sessions.map((s) => (
          <div
            key={s.id}
            className="border rounded p-3 flex items-center justify-between"
          >
            <div>
              <div className="font-mono text-sm">{s.id.slice(0, 8)}</div>
              <div className="text-xs text-gray-500">
                Paper: {s.paper_card_id.slice(0, 8)}
              </div>
            </div>
            <StatusBadge status={s.status} />
          </div>
        ))}
        {sessions.length === 0 && (
          <p className="text-gray-400 text-sm">No analysis sessions yet.</p>
        )}
      </div>
    </div>
  );
}
