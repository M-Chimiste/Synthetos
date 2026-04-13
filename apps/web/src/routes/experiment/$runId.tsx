import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  type RunTelemetry,
  fetchRunRecord,
  fetchRunTelemetry,
  fetchVerificationReport,
  fetchFailurePostmortem,
  controlRun,
} from "../../api/experiment";
import StatusBadge from "../../components/StatusBadge";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export const Route = createFileRoute("/experiment/$runId")({
  component: RunDetailPage,
});

function RunDetailPage() {
  const { runId } = Route.useParams();
  const qc = useQueryClient();

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => fetchRunRecord(runId),
    enabled: !!runId,
    refetchInterval: 3_000,
  });

  const telemetry = useQuery({
    queryKey: ["run-telemetry", runId],
    queryFn: () => fetchRunTelemetry(runId, { limit: 50 }),
    enabled: !!runId,
  });
  const [liveTelemetry, setLiveTelemetry] = useState(telemetry.data ?? []);

  useEffect(() => {
    setLiveTelemetry(telemetry.data ?? []);
  }, [telemetry.data]);

  useEffect(() => {
    if (!runId) return undefined;
    const source = new EventSource(`${BASE_URL}/runs/${runId}/telemetry/stream`);
    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as RunTelemetry;
        setLiveTelemetry((current) => {
          if (current.some((item) => item.id === parsed.id)) return current;
          return [...current, parsed].slice(-100);
        });
      } catch {
        // Ignore malformed frames and keep the existing tail.
      }
    };
    source.addEventListener("done", () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId]);

  const verification = useQuery({
    queryKey: ["verification", runId],
    queryFn: () => fetchVerificationReport(runId).catch(() => null),
    enabled: !!runId,
  });

  const postmortem = useQuery({
    queryKey: ["postmortem", runId],
    queryFn: () => fetchFailurePostmortem(runId).catch(() => null),
    enabled: !!runId,
  });

  const control = useMutation({
    mutationFn: (action: string) => controlRun(runId, action),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["run", runId] });
      void qc.invalidateQueries({ queryKey: ["run-records"] });
    },
  });

  if (run.isLoading) return <div className="p-4">Loading run...</div>;
  if (run.error) return <div className="p-4 text-red-500">Error loading run</div>;
  if (!run.data) return <div className="p-4">Run not found</div>;

  const r = run.data;
  const isRunning = r.status === "running";
  const isPaused = r.status === "paused";
  const isFailed = r.status === "failed";
  const isCancelled = r.status === "cancelled";
  const telemetryItems = useMemo(
    () => [...liveTelemetry].sort((a, b) => a.timestamp.localeCompare(b.timestamp)),
    [liveTelemetry],
  );

  return (
    <div className="p-4 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          Run #{r.run_number}{" "}
          <span className="text-sm font-mono text-gray-500">{r.id.slice(0, 12)}</span>
        </h1>
        <StatusBadge status={r.status} />
      </div>

      {/* Run details */}
      <section className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-gray-500">Image:</span> {r.image_ref || "—"}
        </div>
        <div>
          <span className="text-gray-500">Exit code:</span>{" "}
          {r.exit_code ?? "—"}
        </div>
        <div>
          <span className="text-gray-500">Failure class:</span>{" "}
          {r.failure_class || "—"}
        </div>
        <div>
          <span className="text-gray-500">Command:</span>{" "}
          {r.command || "—"}
        </div>
        {r.error && (
          <div className="col-span-2 text-red-600">
            <span className="text-gray-500">Error:</span> {r.error}
          </div>
        )}
      </section>

      {/* Controls */}
      <section className="flex gap-2">
        {isRunning && (
          <>
            <button
              className="px-3 py-1 bg-yellow-500 text-white rounded text-sm"
              onClick={() => control.mutate("pause")}
              disabled={control.isPending}
            >
              Pause
            </button>
            <button
              className="px-3 py-1 bg-red-500 text-white rounded text-sm"
              onClick={() => control.mutate("cancel")}
              disabled={control.isPending}
            >
              Cancel
            </button>
          </>
        )}
        {isPaused && (
          <>
            <button
              className="px-3 py-1 bg-green-500 text-white rounded text-sm"
              onClick={() => control.mutate("resume")}
              disabled={control.isPending}
            >
              Resume
            </button>
            <button
              className="px-3 py-1 bg-red-500 text-white rounded text-sm"
              onClick={() => control.mutate("cancel")}
              disabled={control.isPending}
            >
              Cancel
            </button>
          </>
        )}
        {(isFailed || isCancelled) && (
          <button
            className="px-3 py-1 bg-blue-500 text-white rounded text-sm"
            onClick={() => control.mutate("retry")}
            disabled={control.isPending}
          >
            Retry
          </button>
        )}
      </section>

      {/* Metrics */}
      {r.metrics_output && Object.keys(r.metrics_output).length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-2">Metrics</h2>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(r.metrics_output).map(([name, value]) => (
              <div key={name} className="border rounded p-2 text-center">
                <div className="text-xs text-gray-500">{name}</div>
                <div className="text-lg font-mono">
                  {typeof value === "number" ? value.toFixed(4) : String(value)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Verification Report */}
      {verification.data && (
        <section>
          <h2 className="text-lg font-semibold mb-2">Verification</h2>
          <div className="border rounded p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-medium">Verdict:</span>
              <StatusBadge status={verification.data.verdict} />
            </div>
            <div className="text-sm">{verification.data.summary}</div>
            {verification.data.warnings?.map((w, i) => (
              <div key={i} className="text-sm text-yellow-600">
                Warning: {w}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Failure Postmortem */}
      {postmortem.data && (
        <section>
          <h2 className="text-lg font-semibold mb-2">Failure Postmortem</h2>
          <div className="border rounded p-3 space-y-2">
            <div>
              <span className="text-gray-500">Failure class:</span>{" "}
              {postmortem.data.failure_class}
            </div>
            <div>
              <span className="text-gray-500">Root cause:</span>{" "}
              {postmortem.data.root_cause}
            </div>
            {postmortem.data.next_step_recommendation && (
              <div>
                <span className="text-gray-500">Next step:</span>{" "}
                {postmortem.data.next_step_recommendation}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Telemetry tail */}
      <section>
        <h2 className="text-lg font-semibold mb-2">
          Recent Telemetry ({telemetryItems.length})
        </h2>
        <div className="bg-gray-900 text-green-400 p-3 rounded font-mono text-xs max-h-64 overflow-y-auto">
          {telemetryItems.map((t) => (
            <div key={t.id}>
              <span className="text-gray-500">
                {new Date(t.timestamp).toLocaleTimeString()}
              </span>{" "}
              [{t.event_type}]{" "}
              {(t.payload as Record<string, unknown>).message as string ?? JSON.stringify(t.payload)}
            </div>
          ))}
          {telemetryItems.length === 0 && (
            <span className="text-gray-500">No telemetry yet.</span>
          )}
        </div>
      </section>

      {/* Resource usage */}
      {r.resource_usage && (
        <section>
          <h2 className="text-lg font-semibold mb-2">Resource Usage</h2>
          <div className="text-sm">
            {Object.entries(r.resource_usage).map(([k, v]) => (
              <div key={k}>
                <span className="text-gray-500">{k}:</span> {String(v)}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
