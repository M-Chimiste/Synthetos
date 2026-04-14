import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAutonomyBudget,
  fetchAutonomyPolicy,
  fetchLoopDecisions,
  resumeAutonomyGate,
  stopAutonomyLoop,
  type AutonomyBudget,
  type AutonomyPolicy,
  type LoopDecision,
} from "../api/autonomy";
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

  const resumeMut = useMutation({
    mutationFn: () => resumeAutonomyGate(cycleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["autonomy"] });
    },
  });

  const stopMut = useMutation({
    mutationFn: () => stopAutonomyLoop(cycleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["autonomy"] });
    },
  });

  if (policyQ.isLoading) {
    return <p className="text-sm text-gray-500">Loading autonomy state...</p>;
  }

  if (policyQ.error || !policyQ.data) {
    return (
      <p className="text-sm text-gray-500">
        Autonomy state unavailable for this cycle.
      </p>
    );
  }

  const policy = policyQ.data;
  const budget = budgetQ.data ?? null;
  const decisions = decisionsQ.data ?? [];

  const lastDecision = decisions[decisions.length - 1];
  const isPausedAtGate = lastDecision?.decision === "stop_gate";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Autonomy</h2>
          <StatusBadge status={policy.mode} />
          {isPausedAtGate && <StatusBadge status="paused" />}
        </div>
        <div className="flex gap-2">
          {isPausedAtGate && (
            <button
              type="button"
              onClick={() => resumeMut.mutate()}
              disabled={resumeMut.isPending}
              className="rounded border border-green-300 bg-green-50 px-3 py-1 text-sm text-green-800 hover:bg-green-100 disabled:opacity-50"
            >
              {resumeMut.isPending ? "Resuming..." : "Resume gate"}
            </button>
          )}
          {policy.mode === "autonomous" && (
            <button
              type="button"
              onClick={() => {
                if (confirm("Stop the autonomous loop?")) {
                  stopMut.mutate();
                }
              }}
              disabled={stopMut.isPending}
              className="rounded border border-red-300 bg-red-50 px-3 py-1 text-sm text-red-800 hover:bg-red-100 disabled:opacity-50"
            >
              {stopMut.isPending ? "Stopping..." : "Stop loop"}
            </button>
          )}
        </div>
      </div>

      {policy.mode === "supervised" && (
        <p className="text-sm text-gray-500">
          Cycle is in supervised mode. Enable autonomous mode by setting{" "}
          <code className="rounded bg-gray-100 px-1">config.autonomy.mode</code>{" "}
          to <code className="rounded bg-gray-100 px-1">autonomous</code>.
        </p>
      )}

      {policy.mode === "autonomous" && (
        <>
          <PolicySummary policy={policy} />
          <BudgetBars policy={policy} budget={budget} />
          <DecisionsTimeline decisions={decisions} />
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
  if (gates.before_hardware_escalation) activeGates.push("before_hardware_escalation");
  if (gates.before_result_promotion) activeGates.push("before_result_promotion");
  if (gates.before_network_execution) activeGates.push("before_network_execution");

  return (
    <div className="rounded border border-gray-200 p-3 text-sm">
      <div className="mb-1 font-medium">Policy</div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-gray-500">Max total runs</dt>
        <dd>{policy.max_total_runs ?? "unlimited"}</dd>
        <dt className="text-gray-500">Max wall-clock hours</dt>
        <dd>{policy.max_wall_clock_hours ?? "unlimited"}</dd>
        <dt className="text-gray-500">Max runs per hypothesis</dt>
        <dd>{policy.max_runs_per_hypothesis ?? "unlimited"}</dd>
        <dt className="text-gray-500">Summary interval</dt>
        <dd>{policy.summary_interval} runs</dd>
        <dt className="text-gray-500">Active gates</dt>
        <dd>{activeGates.length === 0 ? "none" : activeGates.join(", ")}</dd>
      </dl>
    </div>
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
      <div className="rounded border border-gray-200 p-3 text-sm text-gray-500">
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
    <div className="rounded border border-gray-200 p-3 text-sm">
      <div className="mb-2 font-medium">Budget consumption</div>
      <div className="space-y-3">
        <div>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-gray-500">Runs</span>
            <span>
              {budget.total_runs}
              {policy.max_total_runs && ` / ${policy.max_total_runs}`}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full bg-purple-500"
              style={{ width: `${runPct}%` }}
            />
          </div>
        </div>
        <div>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-gray-500">Wall-clock hours</span>
            <span>
              {hours.toFixed(2)}
              {policy.max_wall_clock_hours && ` / ${policy.max_wall_clock_hours}`}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full bg-fuchsia-500"
              style={{ width: `${hoursPct}%` }}
            />
          </div>
        </div>
        {Object.keys(budget.runs_per_hypothesis).length > 0 && (
          <div>
            <div className="mb-1 text-xs text-gray-500">Runs per hypothesis</div>
            <ul className="space-y-0.5 text-xs">
              {Object.entries(budget.runs_per_hypothesis).map(([cardId, count]) => (
                <li key={cardId} className="flex justify-between">
                  <span className="truncate text-gray-600">{cardId.slice(0, 8)}…</span>
                  <span>{count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionsTimeline({ decisions }: { decisions: LoopDecision[] }) {
  if (decisions.length === 0) {
    return (
      <div className="rounded border border-gray-200 p-3 text-sm text-gray-500">
        No loop decisions yet.
      </div>
    );
  }

  return (
    <div className="rounded border border-gray-200 p-3 text-sm">
      <div className="mb-2 font-medium">
        Loop decisions ({decisions.length})
      </div>
      <ol className="space-y-2">
        {decisions.map((d) => (
          <li key={d.id} className="flex items-start gap-3 text-xs">
            <span className="mt-0.5 inline-block w-8 shrink-0 text-right text-gray-400">
              #{d.iteration_number}
            </span>
            <StatusBadge status={d.decision} />
            <span className="flex-1 text-gray-700">
              {d.reasoning}
              {d.gate_triggered && (
                <span className="ml-1 text-fuchsia-700">
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
