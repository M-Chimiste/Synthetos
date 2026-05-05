import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  useConsolidatePatterns,
  useDecayPatterns,
  usePatterns,
} from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";

export const Route = createFileRoute("/patterns/")({
  component: PatternsPage,
});

const PATTERN_TYPES: string[] = [
  "",
  "failure",
  "remediation",
  "signal_trajectory",
  "successful_line",
  "retrieval_heuristic",
];

const TRUST_TIERS: string[] = ["", "auto", "curated", "deprecated"];

function PatternsPage() {
  const [patternType, setPatternType] = useState("");
  const [trustTier, setTrustTier] = useState("");
  const filters: { pattern_type?: string; trust_tier?: string } = {};
  if (patternType) filters.pattern_type = patternType;
  if (trustTier) filters.trust_tier = trustTier;

  const { data, isLoading, error } = usePatterns(filters);
  const consolidate = useConsolidatePatterns();
  const decay = useDecayPatterns();
  const items = data?.items ?? [];

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 24,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.015em",
              margin: 0,
            }}
          >
            Patterns
          </h1>
          <div
            style={{ color: "var(--c-ink-3)", fontSize: 13.5, marginTop: 4 }}
          >
            Canonical knowledge the system has learned across charters.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn"
            onClick={() => decay.mutate({ force: true })}
            disabled={decay.isPending}
          >
            {decay.isPending ? "Enqueuing…" : "Run decay"}
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => consolidate.mutate({})}
            disabled={consolidate.isPending}
          >
            {consolidate.isPending ? "Enqueuing…" : "Consolidate now"}
          </button>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 14,
          flexWrap: "wrap",
        }}
      >
        <FilterChips
          values={PATTERN_TYPES}
          active={patternType}
          onChange={setPatternType}
          labelFor={(v) =>
            v ? v.replace(/_/g, " ") : "All"
          }
        />
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: 6,
            alignItems: "center",
            fontSize: 12.5,
            color: "var(--c-ink-3)",
          }}
        >
          <span>Trust</span>
          <FilterChips
            values={TRUST_TIERS}
            active={trustTier}
            onChange={setTrustTier}
            labelFor={(v) => v || "any"}
          />
        </div>
      </div>

      {(consolidate.isSuccess || decay.isSuccess) && (
        <div
          className="card"
          style={{
            padding: 12,
            marginBottom: 16,
            borderColor: "var(--c-ok-soft)",
            color: "var(--c-ok)",
            background: "var(--c-ok-soft)",
            fontSize: 13,
          }}
        >
          Job enqueued. Patterns refresh once the worker completes the run.
        </div>
      )}

      {error && (
        <div
          className="card"
          style={{
            padding: 14,
            marginBottom: 16,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          {error.message}
        </div>
      )}

      {isLoading && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Loading patterns…
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <div
          className="card"
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--c-ink-3)",
            fontSize: 13.5,
          }}
        >
          No patterns yet. Run consolidation after at least one cycle closes.
        </div>
      )}

      {items.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 140px 90px 80px 80px 80px 80px",
              padding: "10px 16px",
              borderBottom: "1px solid var(--c-line)",
              fontSize: 11,
              color: "var(--c-ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 500,
            }}
          >
            <span>Title</span>
            <span>Type</span>
            <span>Trust</span>
            <span style={{ textAlign: "right" }}>Conf</span>
            <span style={{ textAlign: "right" }}>Evidence</span>
            <span style={{ textAlign: "right" }}>Charters</span>
            <span style={{ textAlign: "right" }}>Stale</span>
          </div>
          {items.map((p, i) => (
            <Link
              key={p.id}
              to="/patterns/$patternId"
              params={{ patternId: p.id }}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 140px 90px 80px 80px 80px 80px",
                padding: "12px 16px",
                borderBottom:
                  i < items.length - 1
                    ? "1px solid var(--c-line-soft)"
                    : "none",
                alignItems: "center",
                fontSize: 13.5,
                textDecoration: "none",
                color: "inherit",
              }}
            >
              <div>
                <div>{p.title}</div>
                <div
                  className="mono"
                  style={{
                    fontSize: 11,
                    color: "var(--c-ink-4)",
                    marginTop: 2,
                  }}
                >
                  {p.id}
                </div>
              </div>
              <span
                className="chip"
                style={{ fontSize: 10.5, textTransform: "capitalize" }}
              >
                {p.pattern_type.replace(/_/g, " ")}
              </span>
              <StatusBadge status={p.trust_tier} />
              <span
                style={{
                  textAlign: "right",
                  fontFamily: "var(--f-mono)",
                  fontSize: 12,
                  color:
                    p.confidence > 0.8 ? "var(--c-ok)" : "var(--c-ink-2)",
                }}
              >
                {p.confidence.toFixed(2)}
              </span>
              <span
                style={{
                  textAlign: "right",
                  fontFamily: "var(--f-mono)",
                  fontSize: 12,
                  color: "var(--c-ink-2)",
                }}
              >
                {p.evidence_count}
              </span>
              <span
                style={{
                  textAlign: "right",
                  fontFamily: "var(--f-mono)",
                  fontSize: 12,
                  color: "var(--c-ink-2)",
                }}
              >
                {p.source_charter_ids.length}
              </span>
              <span
                style={{
                  textAlign: "right",
                  fontFamily: "var(--f-mono)",
                  fontSize: 12,
                  color:
                    p.staleness_score > 0.5
                      ? "var(--c-warn)"
                      : "var(--c-ink-4)",
                }}
              >
                {p.staleness_score.toFixed(2)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChips({
  values,
  active,
  onChange,
  labelFor,
}: {
  values: string[];
  active: string;
  onChange: (v: string) => void;
  labelFor: (v: string) => string;
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {values.map((v) => {
        const isActive = v === active;
        return (
          <button
            key={v || "all"}
            type="button"
            onClick={() => onChange(v)}
            className="btn sm"
            style={{
              background: isActive ? "var(--c-ink)" : "var(--c-bg-elev)",
              color: isActive ? "var(--c-bg)" : "var(--c-ink-2)",
              borderColor: isActive ? "var(--c-ink)" : "var(--c-line)",
              textTransform: "capitalize",
            }}
          >
            {labelFor(v)}
          </button>
        );
      })}
    </div>
  );
}
