"""loop_report operator -- generates a completion report when the autonomous
loop terminates, then transitions the cycle to closed.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select

from libs.core.config import get_settings
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.autonomy import AutonomyBudget, LoopDecision
from libs.storage.models.experiment import (
    HypothesisCard,
)
from libs.storage.models.remediation import (
    MetricFrontier,
    RemediationAction,
)

log = get_logger("autonomy.loop_report")


def loop_report_operator(op_input: OperatorInput) -> OperatorResult:
    """Generate a completion report and close the cycle."""
    factory = get_sync_session_factory()
    cycle_id_raw = op_input.payload.get("cycle_id")
    if cycle_id_raw is None:
        return OperatorResult(success=False, error="missing cycle_id in payload")

    cycle_id = UUID(str(cycle_id_raw))
    settings = get_settings()

    with factory() as db:
        # Gather all data for the report
        decisions = (
            db.execute(
                select(LoopDecision)
                .where(LoopDecision.cycle_id == cycle_id)
                .order_by(LoopDecision.iteration_number)
            )
            .scalars()
            .all()
        )

        budget = db.execute(
            select(AutonomyBudget).where(AutonomyBudget.cycle_id == cycle_id)
        ).scalar_one_or_none()

        cards = (
            db.execute(
                select(HypothesisCard).where(HypothesisCard.cycle_id == cycle_id)
            )
            .scalars()
            .all()
        )

        charter_id = op_input.charter_id
        frontiers = (
            db.execute(
                select(MetricFrontier).where(MetricFrontier.charter_id == charter_id)
            )
            .scalars()
            .all()
        )
        frontier_map = {str(f.hypothesis_card_id): f for f in frontiers}

        remediation_total = db.execute(
            select(func.count())
            .select_from(RemediationAction)
            .where(RemediationAction.cycle_id == cycle_id)
        ).scalar_one()
        remediation_resolved = db.execute(
            select(func.count())
            .select_from(RemediationAction)
            .where(RemediationAction.cycle_id == cycle_id)
            .where(RemediationAction.outcome == "retry_created")
        ).scalar_one()

        # Build report
        report_md = _render_markdown(
            decisions=decisions,
            budget=budget,
            cards=cards,
            frontier_map=frontier_map,
            remediation_total=remediation_total,
            remediation_resolved=remediation_resolved,
        )

        report_json = _render_json(
            decisions=decisions,
            budget=budget,
            cards=cards,
            frontier_map=frontier_map,
            remediation_total=remediation_total,
            remediation_resolved=remediation_resolved,
        )

        # Write to disk
        report_dir = (
            settings.data_root / "reports" / "cycles" / str(cycle_id) / "completion"
        )
        report_dir.mkdir(parents=True, exist_ok=True)

        md_path = report_dir / "report.md"
        md_path.write_text(report_md, encoding="utf-8")

        json_path = report_dir / "report.json"
        json_path.write_text(
            json.dumps(report_json, indent=2, default=str), encoding="utf-8"
        )

        emit_event_sync(
            db,
            event_type="autonomy.completion_report_generated",
            charter_id=charter_id,
            cycle_id=cycle_id,
            payload={
                "report_path": str(md_path),
                "iterations": len(decisions),
            },
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Completion report generated ({len(decisions)} iterations)",
        state_patch={"cycle_status": CycleStatus.closed.value},
        artifacts=[str(md_path), str(json_path)],
    )


def _render_markdown(*, decisions, budget, cards, frontier_map,
                     remediation_total, remediation_resolved) -> str:
    lines = ["# Autonomous Loop Completion Report", ""]

    # Budget summary
    lines.append("## Budget Consumption")
    if budget:
        lines.append(f"- **Total runs:** {budget.total_runs}")
        hours = budget.wall_clock_elapsed_s / 3600.0
        lines.append(f"- **Wall-clock time:** {hours:.2f} hours")
    lines.append("")

    # Hypotheses explored
    lines.append("## Hypotheses Explored")
    lines.append("")
    lines.append("| Hypothesis | Status | Runs | Best Metric | Runs Since Improvement |")
    lines.append("|---|---|---|---|---|")
    for card in cards:
        frontier = frontier_map.get(str(card.id))
        best = frontier.best_metric_value if frontier else "N/A"
        runs = frontier.total_runs if frontier else 0
        rsi = frontier.runs_since_improvement if frontier else "N/A"
        lines.append(f"| {card.title[:60]} | {card.status} | {runs} | {best} | {rsi} |")
    lines.append("")

    # Loop decisions
    lines.append("## Loop Decisions")
    lines.append("")
    lines.append("| # | Decision | Reasoning |")
    lines.append("|---|---|---|")
    for d in decisions:
        reasoning_short = d.reasoning[:80] if d.reasoning else ""
        lines.append(f"| {d.iteration_number} | {d.decision} | {reasoning_short} |")
    lines.append("")

    # Remediation
    lines.append("## Remediation Summary")
    lines.append(f"- **Total attempts:** {remediation_total}")
    lines.append(f"- **Resolved:** {remediation_resolved}")
    lines.append("")

    # Final decision
    if decisions:
        last = decisions[-1]
        lines.append("## Final Decision")
        lines.append(f"- **Decision:** {last.decision}")
        lines.append(f"- **Reasoning:** {last.reasoning}")
    lines.append("")

    return "\n".join(lines)


def _render_json(*, decisions, budget, cards, frontier_map,
                 remediation_total, remediation_resolved) -> dict:
    return {
        "budget": {
            "total_runs": budget.total_runs if budget else 0,
            "wall_clock_elapsed_s": budget.wall_clock_elapsed_s if budget else 0,
            "runs_per_hypothesis": budget.runs_per_hypothesis if budget else {},
        },
        "hypotheses": [
            {
                "card_id": str(c.id),
                "title": c.title,
                "status": c.status,
                "frontier": {
                    "best_metric_value": frontier_map[str(c.id)].best_metric_value,
                    "total_runs": frontier_map[str(c.id)].total_runs,
                    "runs_since_improvement": frontier_map[str(c.id)].runs_since_improvement,
                } if str(c.id) in frontier_map else None,
            }
            for c in cards
        ],
        "decisions": [
            {
                "iteration": d.iteration_number,
                "decision": d.decision,
                "reasoning": d.reasoning,
                "gate_triggered": d.gate_triggered,
            }
            for d in decisions
        ],
        "remediation": {
            "total_attempts": remediation_total,
            "resolved": remediation_resolved,
        },
    }
