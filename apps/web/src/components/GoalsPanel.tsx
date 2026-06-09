import { Link } from "@tanstack/react-router";
import { useState } from "react";

import type { GoalAttempt, GoalResultSummary, ResearchGoal } from "../api/goals";
import {
  useGoalAttempts,
  useGoalReport,
  useGoalResults,
  useGoals,
  useStopGoal,
} from "../api/hooks";
import Markdown from "./Markdown";
import StatusBadge from "./StatusBadge";
import { activeGoals, criteriaRatio, isActiveGoalStatus } from "./goalsPresentation";

export function GoalSummaryCard({ goals }: { goals: ResearchGoal[] }) {
  const active = activeGoals(goals);
  if (active.length === 0) return null;
  return (
    <div className="card" style={{ padding: 20, marginBottom: 20 }}>
      <div className="section-label" style={{ marginBottom: 10 }}>
        Active goals
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {active.slice(0, 3).map((goal) => (
          <div
            key={goal.id}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 12,
              alignItems: "start",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13.5,
                  fontWeight: 600,
                  color: "var(--c-ink)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {goal.title}
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "var(--c-ink-3)",
                  marginTop: 2,
                  lineHeight: 1.45,
                }}
              >
                {goal.summary || goal.goal_statement}
              </div>
            </div>
            <StatusBadge status={goal.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GoalsPanel({ charterId }: { charterId: string }) {
  const goalsQ = useGoals(charterId);
  const goals = goalsQ.data?.items ?? [];

  if (goalsQ.isLoading) {
    return <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>Loading goals…</div>;
  }

  if (goalsQ.error) {
    return (
      <div className="card" style={{ padding: 14, color: "var(--c-err)" }}>
        Failed to load goals: {goalsQ.error.message}
      </div>
    );
  }

  if (goals.length === 0) {
    return (
      <div
        className="card"
        style={{ padding: 32, textAlign: "center", color: "var(--c-ink-3)" }}
      >
        No goals yet.
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {goals.map((goal) => (
        <GoalRow key={goal.id} goal={goal} />
      ))}
    </div>
  );
}

function GoalRow({ goal }: { goal: ResearchGoal }) {
  const [expanded, setExpanded] = useState(false);
  const attemptsQ = useGoalAttempts(goal.id, expanded);
  const reportQ = useGoalReport(goal.id, expanded && Boolean(goal.report_path));
  const resultsQ = useGoalResults(goal.id, expanded);
  const stopGoal = useStopGoal();
  const attempts = attemptsQ.data ?? [];
  const criteriaCount = goal.success_criteria.length;

  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div
        style={{
          padding: 16,
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 16,
          alignItems: "start",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
              {goal.title}
            </h3>
            <StatusBadge status={goal.status} />
          </div>
          <p
            style={{
              margin: "6px 0 0",
              color: "var(--c-ink-2)",
              fontSize: 13,
              lineHeight: 1.55,
            }}
          >
            {goal.goal_statement}
          </p>
          <div
            style={{
              marginTop: 8,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              color: "var(--c-ink-3)",
              fontSize: 11.5,
            }}
          >
            <span>{criteriaCount} criteria</span>
            <span>max {goal.policy.max_attempt_cycles} attempts</span>
            {goal.summary && <span>{goal.summary}</span>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {isActiveGoalStatus(goal.status) && (
            <button
              type="button"
              className="btn sm"
              disabled={stopGoal.isPending}
              onClick={() => {
                if (confirm("Stop this goal and cancel queued goal work?")) {
                  stopGoal.mutate(goal.id);
                }
              }}
            >
              {stopGoal.isPending ? "Stopping…" : "Stop"}
            </button>
          )}
          <button
            type="button"
            className="btn sm"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Hide" : "Open"}
          </button>
        </div>
      </div>

      {expanded && (
        <div style={{ borderTop: "1px solid var(--c-line)", padding: 16 }}>
          <AttemptTable attempts={attempts} loading={attemptsQ.isLoading} />
          <GoalOutputs
            result={resultsQ.data}
            loading={resultsQ.isLoading}
            error={resultsQ.error}
          />
          {goal.report_path && (
            <div style={{ marginTop: 16 }}>
              <div className="section-label" style={{ marginBottom: 8 }}>
                Goal report
              </div>
              <div className="card" style={{ padding: 16 }}>
                {reportQ.isLoading && (
                  <div style={{ color: "var(--c-ink-3)", fontSize: 13 }}>
                    Loading report…
                  </div>
                )}
                {reportQ.data?.markdown && <Markdown>{reportQ.data.markdown}</Markdown>}
                {reportQ.error && (
                  <div style={{ color: "var(--c-ink-3)", fontSize: 13 }}>
                    Report unavailable.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GoalOutputs({
  result,
  loading,
  error,
}: {
  result: GoalResultSummary | undefined;
  loading: boolean;
  error: Error | null;
}) {
  if (loading) {
    return (
      <div style={{ marginTop: 16, color: "var(--c-ink-3)", fontSize: 13 }}>
        Loading outputs…
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ marginTop: 16, color: "var(--c-ink-3)", fontSize: 13 }}>
        Outputs unavailable.
      </div>
    );
  }
  if (!result) return null;

  const runs = result.attempts.flatMap((attempt) => attempt.runs);
  const artifacts = runs.flatMap((run) => run.artifacts.map((artifact) => ({ run, artifact })));
  const metricRows = Object.entries(result.metrics);

  return (
    <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <div className="section-label">Outputs</div>
        <StatusBadge status={result.publication_readiness} />
        <span style={{ fontSize: 12, color: "var(--c-ink-3)" }}>
          {runs.length} runs · {artifacts.length} artifacts
        </span>
      </div>

      <div style={{ fontSize: 13, color: "var(--c-ink-2)", lineHeight: 1.55 }}>
        {result.interpretation}
      </div>

      {result.caveats.length > 0 && (
        <div style={{ color: "var(--c-warn)", fontSize: 12.5, lineHeight: 1.5 }}>
          {result.caveats.slice(0, 3).map((caveat) => (
            <div key={caveat}>{caveat}</div>
          ))}
        </div>
      )}

      {metricRows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(160px, 0.5fr) 1fr",
              minWidth: 520,
              gap: 12,
              fontSize: 12.5,
            }}
          >
            {metricRows.map(([name, values]) => (
              <div
                key={name}
                style={{ display: "contents" }}
              >
                <span className="mono" style={{ color: "var(--c-ink)" }}>
                  {name}
                </span>
                <span style={{ color: "var(--c-accent-ink)" }}>
                  {values.map(formatMetricValue).join(" · ")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {artifacts.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "120px minmax(180px, 1fr) 90px 90px 120px",
              gap: 12,
              minWidth: 720,
              fontSize: 11,
              color: "var(--c-ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 500,
              paddingBottom: 8,
            }}
          >
            <span>Run</span>
            <span>Artifact</span>
            <span>Type</span>
            <span>Size</span>
            <span>Link</span>
          </div>
          {artifacts.slice(0, 12).map(({ run, artifact }) => (
            <div
              key={`${run.run_id}-${artifact.artifact_id}`}
              style={{
                display: "grid",
                gridTemplateColumns: "120px minmax(180px, 1fr) 90px 90px 120px",
                gap: 12,
                minWidth: 720,
                padding: "8px 0",
                borderTop: "1px solid var(--c-line-soft)",
                alignItems: "center",
                fontSize: 12.5,
              }}
            >
              <Link
                to="/experiment/$runId"
                params={{ runId: run.run_id }}
                className="mono"
                style={{ color: "var(--c-accent-ink)", textDecoration: "none" }}
              >
                {run.run_id.slice(0, 12)}
              </Link>
              <span
                title={artifact.path}
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {artifact.name}
              </span>
              <span>{artifact.artifact_type}</span>
              <span>{formatBytes(artifact.size_bytes)}</span>
              <a href={artifact.download_url} style={{ color: "var(--c-accent-ink)" }}>
                Download
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatMetricValue(value: unknown): string {
  return typeof value === "number" ? value.toFixed(4) : String(value);
}

function formatBytes(value: number | null): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function AttemptTable({
  attempts,
  loading,
}: {
  attempts: GoalAttempt[];
  loading: boolean;
}) {
  if (loading) {
    return <div style={{ color: "var(--c-ink-3)", fontSize: 13 }}>Loading attempts…</div>;
  }
  if (attempts.length === 0) {
    return <div style={{ color: "var(--c-ink-3)", fontSize: 13 }}>No attempts yet.</div>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "72px 120px 1fr 1.2fr 90px 110px",
          gap: 12,
          minWidth: 920,
          fontSize: 11,
          color: "var(--c-ink-3)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          fontWeight: 500,
          paddingBottom: 8,
        }}
      >
        <span>Attempt</span>
        <span>Status</span>
        <span>Cycle</span>
        <span>Latest</span>
        <span>Criteria</span>
        <span>Created</span>
      </div>
      {attempts.map((attempt) => {
        const ledger = attempt.evaluation?.status_ledger;
        const latest = ledger?.latest;
        const latestText =
          attempt.evaluation?.blocked_reason ||
          latest?.summary ||
          attempt.evaluation?.summary ||
          "—";
        const ledgerPath = ledger?.markdown_path || ledger?.json_path;
        return (
          <div
            key={attempt.id}
            style={{
              display: "grid",
              gridTemplateColumns: "72px 120px 1fr 1.2fr 90px 110px",
              gap: 12,
              minWidth: 920,
              padding: "9px 0",
              borderTop: "1px solid var(--c-line-soft)",
              alignItems: "center",
              fontSize: 12.5,
            }}
          >
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              #{attempt.attempt_number}
            </span>
            <StatusBadge status={attempt.status} />
            <Link
              to="/cycles/$cycleId/timeline"
              params={{ cycleId: attempt.cycle_id }}
              className="mono"
              style={{ color: "var(--c-accent-ink)", textDecoration: "none" }}
            >
              {attempt.cycle_id}
            </Link>
            <span
              title={ledgerPath || latestText}
              style={{
                color: latest?.outcome === "duplicate_rejected" ? "var(--c-warn)" : "var(--c-ink-2)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {latest?.stage ? `${latest.stage}: ${latestText}` : latestText}
            </span>
            <span>{criteriaRatio(attempt)}</span>
            <span style={{ color: "var(--c-ink-3)" }}>
              {new Date(attempt.created_at).toLocaleDateString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}
