import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  fetchHypothesisCards,
  fetchExperimentSpecs,
  fetchRunRecords,
} from "../../api/experiment";
import { fetchCharterFrontiers, type MetricFrontier } from "../../api/remediation";
import StatusBadge from "../../components/StatusBadge";

export const Route = createFileRoute("/experiment/")({
  component: ExperimentIndex,
});

function ExperimentIndex() {
  const hypotheses = useQuery({
    queryKey: ["hypothesis-cards"],
    queryFn: () => fetchHypothesisCards({ limit: 20 }),
  });

  const specs = useQuery({
    queryKey: ["experiment-specs"],
    queryFn: () => fetchExperimentSpecs({ limit: 20 }),
  });

  const runs = useQuery({
    queryKey: ["run-records"],
    queryFn: () => fetchRunRecords({ limit: 20 }),
    refetchInterval: 5_000,
  });

  // Derive charter_id from first hypothesis card (all cards share a charter)
  const charterId = hypotheses.data?.items?.[0]?.charter_id;

  const frontiers = useQuery({
    queryKey: ["frontiers", charterId],
    queryFn: () => fetchCharterFrontiers(charterId!),
    enabled: !!charterId,
  });

  return (
    <div className="p-4 space-y-6">
      <h1 className="text-2xl font-bold">Experiments</h1>

      {/* Hypotheses */}
      <section>
        <h2 className="text-lg font-semibold mb-2">
          Hypotheses ({hypotheses.data?.total ?? 0})
        </h2>
        {hypotheses.isLoading && <p className="text-sm text-gray-400">Loading...</p>}
        <div className="space-y-2">
          {(hypotheses.data?.items ?? []).map((h) => (
            <div
              key={h.id}
              className="border rounded p-3 flex items-center justify-between"
            >
              <div className="flex-1">
                <div className="font-medium">{h.title}</div>
                <div className="text-xs text-gray-500">
                  {h.rank != null ? `#${h.rank}` : "unranked"}
                  {h.novelty_score != null &&
                    ` · N:${h.novelty_score.toFixed(2)} F:${h.feasibility_score?.toFixed(2)} I:${h.impact_score?.toFixed(2)}`}
                </div>
              </div>
              <StatusBadge status={h.status} />
            </div>
          ))}
          {hypotheses.data?.items.length === 0 && (
            <p className="text-gray-400 text-sm">No hypotheses yet.</p>
          )}
        </div>
      </section>

      {/* Experiment Specs */}
      <section>
        <h2 className="text-lg font-semibold mb-2">
          Experiment Specs ({specs.data?.total ?? 0})
        </h2>
        {specs.isLoading && <p className="text-sm text-gray-400">Loading...</p>}
        <div className="space-y-2">
          {(specs.data?.items ?? []).map((s) => (
            <div
              key={s.id}
              className="border rounded p-3 flex items-center justify-between"
            >
              <div>
                <div className="font-medium">{s.title}</div>
                <div className="text-xs text-gray-500">
                  {s.metrics.length} metric(s) ·{" "}
                  {s.base_image || "default image"}
                </div>
              </div>
              <StatusBadge status={s.status} />
            </div>
          ))}
          {specs.data?.items.length === 0 && (
            <p className="text-gray-400 text-sm">No specs yet.</p>
          )}
        </div>
      </section>

      {/* Runs */}
      <section>
        <h2 className="text-lg font-semibold mb-2">
          Runs ({runs.data?.total ?? 0})
        </h2>
        {runs.isLoading && <p className="text-sm text-gray-400">Loading...</p>}
        <div className="space-y-2">
          {(runs.data?.items ?? []).map((r) => (
            <div
              key={r.id}
              className="border rounded p-3 flex items-center justify-between"
            >
              <div>
                <div className="font-mono text-sm">
                  Run #{r.run_number} · {r.id.slice(0, 8)}
                </div>
                <div className="text-xs text-gray-500">
                  {r.exit_code != null && `exit=${r.exit_code} · `}
                  {r.failure_class && `${r.failure_class} · `}
                  {r.image_ref || "no image"}
                </div>
                {r.metrics_output && (
                  <div className="text-xs text-blue-600 mt-1">
                    {Object.entries(r.metrics_output)
                      .map(([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(4) : v}`)
                      .join(" · ")}
                  </div>
                )}
              </div>
              <StatusBadge status={r.status} />
            </div>
          ))}
          {runs.data?.items.length === 0 && (
            <p className="text-gray-400 text-sm">No runs yet.</p>
          )}
        </div>
      </section>

      {/* Frontier Summary */}
      {frontiers.data && frontiers.data.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-2">
            Metric Frontiers ({frontiers.data.length})
          </h2>
          <div className="space-y-2">
            {frontiers.data.map((f: MetricFrontier) => (
              <div
                key={f.id}
                className="border rounded p-3 flex items-center justify-between"
              >
                <div>
                  <div className="font-medium">
                    {f.primary_metric_name}{" "}
                    <span className="text-xs text-gray-500">
                      ({f.primary_metric_direction})
                    </span>
                  </div>
                  <div className="text-sm">
                    Best: {f.best_metric_value.toFixed(4)} ·{" "}
                    {f.successful_runs}/{f.total_runs} runs successful
                  </div>
                </div>
                <div className="text-right text-sm">
                  <div
                    className={
                      f.runs_since_improvement >= 5
                        ? "text-red-600"
                        : f.runs_since_improvement >= 3
                          ? "text-yellow-600"
                          : "text-green-600"
                    }
                  >
                    {f.runs_since_improvement === 0
                      ? "Improved last run"
                      : `${f.runs_since_improvement} runs since improvement`}
                  </div>
                  <a
                    href={`/experiment/${f.best_run_id}`}
                    className="text-xs text-blue-500 underline"
                  >
                    Best run
                  </a>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
