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
from libs.core.event_types import AutonomyEvents, ResultEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.services.job_service import create_job
from libs.core.services.result_introspection import build_cycle_result_introspection
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
from libs.storage.models.research import ResearchCycle

log = get_logger("autonomy.loop_report")


def _enqueue_consolidation_job(
    *,
    factory,
    charter_id: UUID,
    cycle_id: UUID,
) -> None:
    """Enqueue Phase 6 consolidation in a fresh transaction.

    This keeps consolidation scheduling from poisoning the completion-report
    transaction if job creation fails.
    """
    with factory() as db:
        try:
            create_job(
                db,
                cycle_id=cycle_id,
                job_type="consolidate_patterns",
                payload={"charter_id": str(charter_id), "cycle_id": str(cycle_id)},
                priority=0,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            log.warning(
                "loop_report.consolidation_enqueue_failed",
                error=str(exc),
                cycle_id=str(cycle_id),
            )


def _enqueue_goal_evaluation_job(
    *,
    factory,
    charter_id: UUID,
    cycle_id: UUID,
    goal_id: str,
    artifacts: list[str],
) -> None:
    """Enqueue goal evaluation after a goal-linked cycle report."""
    with factory() as db:
        try:
            create_job(
                db,
                cycle_id=cycle_id,
                job_type="goal_evaluate",
                payload={
                    "goal_id": goal_id,
                    "cycle_id": str(cycle_id),
                    "artifacts": artifacts,
                },
                priority=5,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            log.warning(
                "loop_report.goal_evaluation_enqueue_failed",
                error=str(exc),
                cycle_id=str(cycle_id),
                goal_id=goal_id,
            )


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
        cycle = db.get(ResearchCycle, cycle_id)
        goal_cfg = ((cycle.config or {}).get("goal") or {}) if cycle else {}
        goal_id = goal_cfg.get("goal_id")

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

        introspection = build_cycle_result_introspection(
            db,
            cycle_id,
            write_files=True,
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
        emit_event_sync(
            db,
            event_type=ResultEvents.introspection_generated.value,
            charter_id=charter_id,
            cycle_id=cycle_id,
            payload={
                "report_path": introspection.introspection_markdown_path,
                "json_path": introspection.introspection_json_path,
                "publication_readiness": introspection.publication_readiness,
                "run_count": len(introspection.runs),
            },
        )

        db.commit()

    _enqueue_consolidation_job(
        factory=factory,
        charter_id=charter_id,
        cycle_id=cycle_id,
    )
    artifacts = [
        str(paths.markdown),
        str(paths.json),
        str(introspection.introspection_markdown_path),
        str(introspection.introspection_json_path),
    ]
    if goal_id:
        _enqueue_goal_evaluation_job(
            factory=factory,
            charter_id=charter_id,
            cycle_id=cycle_id,
            goal_id=str(goal_id),
            artifacts=artifacts,
        )

    return OperatorResult(
        success=True,
        summary=f"Completion report generated ({len(decisions)} iterations)",
        state_patch={"cycle_status": CycleStatus.closed.value},
        artifacts=artifacts,
    )
