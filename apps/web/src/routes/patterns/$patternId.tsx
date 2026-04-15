import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  useApprovePattern,
  usePattern,
  useRejectPattern,
  useUpdateTrustTier,
} from "../../api/hooks";

export const Route = createFileRoute("/patterns/$patternId")({
  component: PatternDetailPage,
});

function PatternDetailPage() {
  const { patternId } = Route.useParams();
  const { data, isLoading, error } = usePattern(patternId);
  const approve = useApprovePattern();
  const reject = useRejectPattern();
  const updateTier = useUpdateTrustTier();
  const [rationale, setRationale] = useState("");

  return (
    <div>
      <Link to="/patterns" className="text-sm text-gray-500 hover:text-gray-700">
        &larr; Back to patterns
      </Link>

      {isLoading && <p className="mt-4 text-sm text-gray-500">Loading…</p>}
      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      {data && (
        <>
          <h1 className="mt-2 text-2xl font-semibold">{data.title}</h1>
          <p className="mt-1 font-mono text-xs text-gray-500">{data.id}</p>

          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Type" value={data.pattern_type} />
            <Stat label="Trust" value={data.trust_tier} />
            <Stat label="Confidence" value={data.confidence.toFixed(3)} />
            <Stat label="Evidence" value={String(data.evidence_count)} />
            <Stat
              label="Charters"
              value={String(data.source_charter_ids.length)}
            />
            <Stat label="Staleness" value={data.staleness_score.toFixed(2)} />
            <Stat
              label="Last reinforced"
              value={new Date(data.last_reinforced_at).toLocaleString()}
            />
            <Stat
              label="Consolidation v"
              value={String(data.consolidation_version)}
            />
          </div>

          <section className="mt-6">
            <h2 className="text-lg font-semibold">Summary</h2>
            <p className="mt-2 whitespace-pre-wrap rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-800">
              {data.summary || "(none)"}
            </p>
          </section>

          <section className="mt-6">
            <h2 className="text-lg font-semibold">Structured body</h2>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-gray-900 p-4 text-xs text-gray-100">
              {JSON.stringify(data.structured_body, null, 2)}
            </pre>
          </section>

          <section className="mt-6">
            <h2 className="text-lg font-semibold">Curation</h2>
            <textarea
              className="mt-2 w-full rounded-md border border-gray-300 p-2 text-sm"
              rows={3}
              placeholder="Rationale (required for any action)…"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                disabled={!rationale.trim() || approve.isPending}
                onClick={() =>
                  approve.mutate({ id: patternId, rationale: rationale.trim() })
                }
                className="rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-500 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                disabled={!rationale.trim() || reject.isPending}
                onClick={() =>
                  reject.mutate({ id: patternId, rationale: rationale.trim() })
                }
                className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
              >
                Reject
              </button>
              <button
                disabled={!rationale.trim() || updateTier.isPending}
                onClick={() =>
                  updateTier.mutate({
                    id: patternId,
                    trust_tier: "curated",
                    rationale: rationale.trim(),
                  })
                }
                className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                Mark curated
              </button>
              <button
                disabled={!rationale.trim() || updateTier.isPending}
                onClick={() =>
                  updateTier.mutate({
                    id: patternId,
                    trust_tier: "deprecated",
                    rationale: rationale.trim(),
                  })
                }
                className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                Deprecate
              </button>
            </div>
          </section>

          <section className="mt-6">
            <h2 className="text-lg font-semibold">Recent observations</h2>
            {data.recent_observations.length === 0 ? (
              <p className="mt-2 text-sm text-gray-500">No observations yet.</p>
            ) : (
              <ul className="mt-2 divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
                {data.recent_observations.map((o) => (
                  <li key={o.id} className="px-3 py-2 text-sm">
                    <span className="font-mono text-xs text-gray-500">
                      {new Date(o.observed_at).toLocaleString()}
                    </span>{" "}
                    <span className="text-gray-700">
                      [{o.source_artifact_type}] cycle {o.cycle_id.slice(0, 8)}…
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}
