import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  useConsolidatePatterns,
  useDecayPatterns,
  usePatterns,
} from "../../api/hooks";

export const Route = createFileRoute("/patterns/")({
  component: PatternsPage,
});

const PATTERN_TYPES = [
  "",
  "failure",
  "remediation",
  "signal_trajectory",
  "successful_line",
  "retrieval_heuristic",
];

const TRUST_TIERS = ["", "auto", "curated", "deprecated"];

function PatternsPage() {
  const [patternType, setPatternType] = useState("");
  const [trustTier, setTrustTier] = useState("");
  const filters: { pattern_type?: string; trust_tier?: string } = {};
  if (patternType) filters.pattern_type = patternType;
  if (trustTier) filters.trust_tier = trustTier;

  const { data, isLoading, error } = usePatterns(filters);
  const consolidate = useConsolidatePatterns();
  const decay = useDecayPatterns();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Canonical patterns</h1>
        <div className="flex gap-2">
          <button
            onClick={() => consolidate.mutate({})}
            disabled={consolidate.isPending}
            className="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {consolidate.isPending ? "Enqueuing…" : "Consolidate now"}
          </button>
          <button
            onClick={() => decay.mutate({ force: true })}
            disabled={decay.isPending}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            {decay.isPending ? "Enqueuing…" : "Run decay"}
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <FilterSelect
          label="Type"
          value={patternType}
          onChange={setPatternType}
          options={PATTERN_TYPES}
        />
        <FilterSelect
          label="Trust"
          value={trustTier}
          onChange={setTrustTier}
          options={TRUST_TIERS}
        />
      </div>

      {(consolidate.isSuccess || decay.isSuccess) && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          Job enqueued. Patterns refresh once the worker completes the run.
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      {isLoading && <p className="text-sm text-gray-500">Loading patterns…</p>}

      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
          No patterns yet. Run consolidation after at least one cycle closes.
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left">Title</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-left">Trust</th>
                <th className="px-3 py-2 text-right">Conf</th>
                <th className="px-3 py-2 text-right">Evidence</th>
                <th className="px-3 py-2 text-right">Charters</th>
                <th className="px-3 py-2 text-right">Stale</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <Link
                      to="/patterns/$patternId"
                      params={{ patternId: p.id }}
                      className="text-gray-900 hover:underline"
                    >
                      {p.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-gray-600">{p.pattern_type}</td>
                  <td className="px-3 py-2">
                    <TierBadge tier={p.trust_tier} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.confidence.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.evidence_count}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.source_charter_ids.length}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {p.staleness_score.toFixed(2)}
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

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-gray-600">
      {label}:
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-gray-300 px-2 py-1 text-sm"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "(any)"}
          </option>
        ))}
      </select>
    </label>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const styles =
    tier === "auto"
      ? "bg-green-100 text-green-700"
      : tier === "curated"
        ? "bg-yellow-100 text-yellow-700"
        : "bg-gray-200 text-gray-600";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}>
      {tier}
    </span>
  );
}
