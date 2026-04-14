"""loop_report operator -- generates a completion report when the autonomous
loop terminates, then transitions the cycle to closed.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from libs.autonomy.completion_report import (
    build_report_paths,
    generate_executive_summary,
    render_json,
    render_markdown,
    write_report_bundle,
)
from libs.core.config import get_settings
from libs.core.event_types import AutonomyEvents
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
    RunRecommendation,
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

        final_recommendation = None
        if decisions:
            final_recommendation = db.execute(
                select(RunRecommendation).where(
                    RunRecommendation.id == decisions[-1].recommendation_id
                )
            ).scalar_one_or_none()

        report_json = render_json(
            cycle_id=cycle_id,
            budget=budget,
            decisions=list(decisions),
            cards=list(cards),
            frontier_map=frontier_map,
            remediation_total=remediation_total,
            remediation_resolved=remediation_resolved,
            final_recommendation=final_recommendation,
        )
        executive_summary = generate_executive_summary(
            db,
            cycle_id=cycle_id,
            report_json=report_json,
        )
        report_md = render_markdown(
            executive_summary=executive_summary,
            report_json=report_json,
        )

        paths = build_report_paths(settings.data_root, cycle_id)
        write_report_bundle(
            paths,
            markdown=report_md,
            json_payload=report_json,
        )

        emit_event_sync(
            db,
            event_type=AutonomyEvents.completion_report_generated.value,
            charter_id=charter_id,
            cycle_id=cycle_id,
            payload={
                "report_path": str(paths.markdown),
                "iterations": len(decisions),
            },
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Completion report generated ({len(decisions)} iterations)",
        state_patch={"cycle_status": CycleStatus.closed.value},
        artifacts=[str(paths.markdown), str(paths.json)],
    )
