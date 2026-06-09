import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { GoalSummaryCard } from "./GoalsPanel";
import { activeGoals, criteriaRatio } from "./goalsPresentation";
import type { GoalAttempt, ResearchGoal } from "../api/goals";

const baseGoal: ResearchGoal = {
  id: "goal-1",
  charter_id: "charter-1",
  title: "Demonstrate blockwise training",
  goal_statement: "Find a training setup that completes and emits metrics.",
  success_criteria: [
    {
      name: "completed run",
      description: "At least one run completes.",
      required: true,
      check_type: "completed_run_exists",
      params: {},
      scope: "cumulative",
    },
  ],
  policy: {
    max_attempt_cycles: 5,
    max_total_runs: null,
    max_wall_clock_hours: null,
    autonomy: {},
    discovery: {},
  },
  status: "running",
  summary: null,
  report_path: null,
  report_json_path: null,
  created_at: "2026-06-08T00:00:00Z",
  updated_at: "2026-06-08T00:00:00Z",
  completed_at: null,
};

const baseAttempt: GoalAttempt = {
  id: "attempt-1",
  goal_id: "goal-1",
  charter_id: "charter-1",
  cycle_id: "cycle-1",
  attempt_number: 1,
  status: "failed",
  evaluation: null,
  report_path: null,
  report_json_path: null,
  created_at: "2026-06-08T00:00:00Z",
  updated_at: "2026-06-08T00:00:00Z",
  completed_at: null,
};

describe("GoalsPanel helpers", () => {
  it("filters active goals", () => {
    const goals = [
      baseGoal,
      { ...baseGoal, id: "goal-2", status: "satisfied" as const },
      { ...baseGoal, id: "goal-3", status: "exhausted" as const },
    ];

    expect(activeGoals(goals).map((goal) => goal.id)).toEqual(["goal-1"]);
  });

  it("formats criteria ratios", () => {
    expect(criteriaRatio(baseAttempt)).toBe("—");
    expect(
      criteriaRatio({
        ...baseAttempt,
        evaluation: {
          passed: false,
          criteria: [
            { name: "a", passed: true, required: true },
            { name: "b", passed: false, required: true },
          ],
        },
      }),
    ).toBe("1/2");
  });

  it("renders an active goal summary card", () => {
    const markup = renderToStaticMarkup(<GoalSummaryCard goals={[baseGoal]} />);

    expect(markup).toContain("Active goals");
    expect(markup).toContain("Demonstrate blockwise training");
    expect(markup).toContain("running");
  });

  it("renders nothing when there are no active goals", () => {
    const markup = renderToStaticMarkup(
      <GoalSummaryCard goals={[{ ...baseGoal, status: "satisfied" }]} />,
    );

    expect(markup).toBe("");
  });
});
