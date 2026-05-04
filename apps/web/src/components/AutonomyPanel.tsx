import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAutonomyBudget,
  fetchAutonomyPolicy,
  fetchAutonomyReport,
  fetchLoopDecisions,
  type AutonomyReport,
  resumeAutonomyGate,
  stopAutonomyLoop,
  type AutonomyBudget,
  type AutonomyPolicy,
  type LoopDecision,
} from "../api/autonomy";
import Markdown from "./Markdown";
import StatusBadge from "./StatusBadge";

interface Props {
  cycleId: string;
}

export default function AutonomyPanel({ cycleId }: Props) {
  const queryClient = useQueryClient();

  const policyQ = useQuery({
    queryKey: ["autonomy", "policy", cycleId],
    queryFn: () => fetchAutonomyPolicy(cycleId),
  });

  const budgetQ = useQuery({
    queryKey: ["autonomy", "budget", cycleId],
    queryFn: () => fetchAutonomyBudget(cycleId),
    refetchInterval: 5_000,
  });

  const decisionsQ = useQuery({
    queryKey: ["autonomy", "decisions", cycleId],
    queryFn: () => fetchLoopDecisions(cycleId),
    refetchInterval: 5_000,
  });

  const reportQ = useQuery({
    queryKey: ["autonomy", "report", cycleId],
    queryFn: () => fetchAutonomyReport(cycleId),
    retry: false,
  });

  const resumeMut = useMutation({
    mutationFn: () => resumeAutonomyGate(cycleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["autonomy"] });
    },
  });

  const stopMut = useMutation({
    mutationFn: () => stopAutonomyLoop(cycleId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["autonomy"] });
    },
  });

  if (policyQ.isLoading) {
    return (
      <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
        Loading autonomy state…
      </div>
    );
  }

  if (policyQ.error || !policyQ.data) {
    return (
      <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
        Autonomy state unavailable for this cycle.
      </div>
    );
  }

  const policy = policyQ.data;
  const budget = budgetQ.data ?? null;
  const decisions = decisionsQ.data ?? [];

  const lastDecision = decisions[decisions.length - 1];
  const isPausedAtGate = lastDecision?.decision === "stop_gate";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <h2
          style={{
            fontSize: 14,
            fontWeight: 600,
            margin: 0,
            letterSpacing: "-0.005em",
          }}
        >
          Autonomy
        </h2>
        <StatusBadge status={policy.mode} />
        {isPausedAtGate && <StatusBadge status="paused" />}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {isPausedAtGate && (
            <button
              type="button"
              className="btn sm"
              onClick={() => resumeMut.mutate()}
              disabled={resumeMut.isPending}
              style={{
                background: "var(--c-ok-soft)",
                borderColor: "transparent",
                color: "var(--c-ok)",
              }}
            >
              {resumeMut.isPending ? "Resuming…" : "Resume gate"}
            </button>
          )}
          {policy.mode === "autonomous" && (
            <button
              type="button"
              className="btn sm"
              onClick={() => {
                if (confirm("Stop the autonomous loop?")) {
                  stopMut.mutate();
                }
              }}
              disabled={stopMut.isPending}
              style={{
                background: "var(--c-err-soft)",
                borderColor: "transparent",
                color: "var(--c-err)",
              }}
            >
              {stopMut.isPending ? "Stopping…" : "Stop loop"}
            </button>
          )}
        </div>
      </div>

      {policy.mode === "supervised" && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Cycle is in supervised mode. Enable autonomous mode by setting{" "}
          <span className="mono" style={{ color: "var(--c-ink-2)" }}>
            config.autonomy.mode
          </span>{" "}
          to{" "}
          <span className="mono" style={{ color: "var(--c-ink-2)" }}>
            autonomous
          </span>
          .
        </div>
      )}

      {policy.mode === "autonomous" && (
        <>
          <PolicySummary policy={policy} />
          <BudgetBars policy={policy} budget={budget} />
          <DecisionsTimeline decisions={decisions} />
          <ReportViewer
            report={reportQ.data ?? null}
            isLoading={reportQ.isLoading}
          />
        </>
      )}
    </div>
  );
}

function PolicySummary({ policy }: { policy: AutonomyPolicy }) {
  const gates = policy.checkpoint_gates;
  const activeGates: string[] = [];
  if (gates.after_every_run) activeGates.push("after_every_run");
  if (gates.after_every_n_runs)
    activeGates.push(`after_every_${gates.after_every_n_runs}_runs`);
  if (gates.before_hardware_escalation)
    activeGates.push("before_hardware_escalation");
  if (gates.before_result_promotion)
    activeGates.push("before_result_promotion");
  if (gates.before_network_execution)
    activeGates.push("before_network_execution");

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-label" style={{ marginBottom: 10 }}>
        Policy
      </div>
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "max-content 1fr",
          columnGap: 16,
          rowGap: 4,
          margin: 0,
          fontSize: 12.5,
        }}
      >
        <Row label="Max total runs" value={policy.max_total_runs ?? "unlimited"} />
        <Row
          label="Max wall-clock hours"
          value={policy.max_wall_clock_hours ?? "unlimited"}
        />
        <Row
          label="Max runs per hypothesis"
          value={policy.max_runs_per_hypothesis ?? "unlimited"}
        />
        <Row
          label="Summary interval"
          value={`${policy.summary_interval} runs`}
        />
        <Row
          label="Active gates"
          value={activeGates.length === 0 ? "none" : activeGates.join(", ")}
        />
        <Row label="Cost budgets" value={policy.cost_budget_note} />
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <>
      <dt style={{ color: "var(--c-ink-3)" }}>{label}</dt>
      <dd
        style={{
          margin: 0,
          color: "var(--c-ink)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </dd>
    </>
  );
}

function BudgetBars({
  policy,
  budget,
}: {
  policy: AutonomyPolicy;
  budget: AutonomyBudget | null;
}) {
  if (!budget) {
    return (
      <div
        className="card"
        style={{ padding: 14, fontSize: 13, color: "var(--c-ink-3)" }}
      >
        No budget tracking yet. The loop has not started consuming the budget.
      </div>
    );
  }

  const hours = budget.wall_clock_elapsed_s / 3600.0;
  const runPct = policy.max_total_runs
    ? Math.min(100, (budget.total_runs / policy.max_total_runs) * 100)
    : 0;
  const hoursPct = policy.max_wall_clock_hours
    ? Math.min(100, (hours / policy.max_wall_clock_hours) * 100)
    : 0;

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-label" style={{ marginBottom: 12 }}>
        Budget consumption
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Bar
          label="Runs"
          value={
            policy.max_total_runs
              ? `${budget.total_runs} / ${policy.max_total_runs}`
              : String(budget.total_runs)
          }
          pct={runPct}
          color="var(--c-accent)"
        />
        <Bar
          label="Wall-clock hours"
          value={
            policy.max_wall_clock_hours
              ? `${hours.toFixed(2)} / ${policy.max_wall_clock_hours}`
              : hours.toFixed(2)
          }
          pct={hoursPct}
          color="var(--c-violet)"
        />
        {Object.keys(budget.runs_per_hypothesis).length > 0 && (
          <div>
            <div
              style={{
                fontSize: 11.5,
                color: "var(--c-ink-3)",
                marginBottom: 4,
              }}
            >
              Runs per hypothesis
            </div>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {Object.entries(budget.runs_per_hypothesis).map(
                ([cardId, count]) => (
                  <li
                    key={cardId}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 12,
                      color: "var(--c-ink-2)",
                      padding: "2px 0",
                    }}
                  >
                    <span className="mono">{cardId.slice(0, 8)}…</span>
                    <span
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      {count}
                    </span>
                  </li>
                ),
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function Bar({
  label,
  value,
  pct,
  color,
}: {
  label: string;
  value: string;
  pct: number;
  color: string;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          marginBottom: 4,
        }}
      >
        <span style={{ color: "var(--c-ink-3)" }}>{label}</span>
        <span
          style={{
            color: "var(--c-ink-2)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {value}
        </span>
      </div>
      <div
        style={{
          height: 6,
          background: "var(--c-line-soft)",
          borderRadius: 999,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: color,
            transition: "width 200ms ease",
          }}
        />
      </div>
    </div>
  );
}

function DecisionsTimeline({ decisions }: { decisions: LoopDecision[] }) {
  if (decisions.length === 0) {
    return (
      <div
        className="card"
        style={{ padding: 14, fontSize: 13, color: "var(--c-ink-3)" }}
      >
        No loop decisions yet.
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="section-label" style={{ marginBottom: 10 }}>
        Loop decisions ({decisions.length})
      </div>
      <ol
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {decisions.map((d) => (
          <li
            key={d.id}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              fontSize: 12,
            }}
          >
            <span
              className="mono"
              style={{
                width: 28,
                color: "var(--c-ink-4)",
                flexShrink: 0,
                textAlign: "right",
              }}
            >
              #{d.iteration_number}
            </span>
            <StatusBadge status={d.decision} />
            <span style={{ flex: 1, color: "var(--c-ink-2)" }}>
              {d.reasoning}
              {d.gate_triggered && (
                <span
                  style={{ marginLeft: 6, color: "var(--c-violet)" }}
                >
                  (gate: {d.gate_triggered})
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReportViewer({
  report,
  isLoading,
}: {
  report: AutonomyReport | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div
        className="card"
        style={{ padding: 14, fontSize: 13, color: "var(--c-ink-3)" }}
      >
        Loading completion report…
      </div>
    );
  }

  if (!report?.markdown) {
    return (
      <div
        className="card"
        style={{ padding: 14, fontSize: 13, color: "var(--c-ink-3)" }}
      >
        No completion report yet. The report appears when the autonomous loop
        stops.
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="section-label" style={{ marginBottom: 10 }}>
        Completion report
      </div>
      <Markdown>{report.markdown}</Markdown>
    </div>
  );
}
