import type { GoalAttempt, ResearchGoal } from "../api/goals";

const ACTIVE_GOAL_STATUSES = new Set(["created", "running"]);

export function isActiveGoalStatus(status: string): boolean {
  return ACTIVE_GOAL_STATUSES.has(status);
}

export function activeGoals(goals: ResearchGoal[]): ResearchGoal[] {
  return goals.filter((goal) => isActiveGoalStatus(goal.status));
}

export function criteriaRatio(attempt: GoalAttempt): string {
  const criteria = attempt.evaluation?.criteria ?? [];
  if (criteria.length === 0) return "—";
  const passed = criteria.filter((criterion) => criterion.passed).length;
  return `${passed}/${criteria.length}`;
}
