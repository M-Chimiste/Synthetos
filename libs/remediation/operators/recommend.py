"""recommend operator -- produces a next-step recommendation for every
terminal run (both successful and failed-then-exhausted paths).
"""

from __future__ import annotations

from sqlalchemy import func, select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import SignalEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.remediation.operators._common import (
    ExecutionStateError,
    load_experiment_spec,
    load_frontier,
    load_lineage_actions,
    load_lineage_run_ids,
    load_run_record,
    run_record_id_from_payload,
)
from libs.remediation.recommendations import RecommendationInputs, compute_recommendation
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import FailurePostmortem, VerificationReport
from libs.storage.models.remediation import (
    DirectionalSignal,
    RunRecommendation,
)

log = get_logger("remediation.recommend")


def recommend_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    is_failed_path = bool(op_input.payload.get("failed"))

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = load_experiment_spec(db, run.experiment_spec_id)

        # Load signal (may not exist for failed path)
        signal_row = db.execute(
            select(DirectionalSignal).where(
                DirectionalSignal.run_record_id == run.id
            )
        ).scalar_one_or_none()

        # Load frontier
        frontier = load_frontier(db, run.charter_id, spec.hypothesis_card_id)

        lineage_actions = load_lineage_actions(db, run.id)
        lineage_run_ids = load_lineage_run_ids(db, run.id)
        remediation_count = len(lineage_actions)
        remediation_exhausted = any(
            action.outcome == "exhausted" for action in lineage_actions
        )

        # Historical counts stay informative, but only current-lineage failures
        # influence the recommendation type.
        from libs.storage.models.experiment import RunRecord

        historical_postmortem_count = db.execute(
            select(func.count())
            .select_from(FailurePostmortem)
            .join(RunRecord, FailurePostmortem.run_record_id == RunRecord.id)
            .where(RunRecord.experiment_spec_id == spec.id)
        ).scalar_one()

        lineage_postmortem_count = db.execute(
            select(FailurePostmortem)
            .join(RunRecord, FailurePostmortem.run_record_id == RunRecord.id)
            .where(RunRecord.id.in_(lineage_run_ids))
        ).scalars().all()
        has_unresolved = is_failed_path or remediation_exhausted or bool(
            lineage_postmortem_count
        )

        inputs = RecommendationInputs(
            signal=signal_row.signal if signal_row else None,
            runs_since_improvement=frontier.runs_since_improvement if frontier else 0,
            total_runs=frontier.total_runs if frontier else 1,
            successful_runs=frontier.successful_runs if frontier else (0 if is_failed_path else 1),
            remediation_attempts=remediation_count,
            remediation_exhausted=remediation_exhausted,
            has_unresolved_failures=has_unresolved,
            failed=is_failed_path,
        )

        rec = compute_recommendation(inputs)

        # Build inputs_summary snapshot
        inputs_summary = {
            "signal": signal_row.signal if signal_row else None,
            "frontier": {
                "best_metric_value": frontier.best_metric_value,
                "runs_since_improvement": frontier.runs_since_improvement,
                "total_runs": frontier.total_runs,
                "successful_runs": frontier.successful_runs,
            } if frontier else None,
            "remediation_attempts": remediation_count,
            "remediation_exhausted": remediation_exhausted,
            "has_unresolved_failures": has_unresolved,
            "failed_path": is_failed_path,
            "historical_postmortem_count": historical_postmortem_count,
        }

        rec_row = db.execute(
            select(RunRecommendation).where(RunRecommendation.run_record_id == run.id)
        ).scalar_one_or_none()
        if rec_row is None:
            rec_row = RunRecommendation(
                id=uuid7(),
                run_record_id=run.id,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                experiment_spec_id=spec.id,
                recommendation_type=rec.recommendation_type,
                action=rec.action,
                reasoning=rec.reasoning,
                inputs_summary=inputs_summary,
                created_at=utcnow(),
            )
            db.add(rec_row)
        else:
            rec_row.recommendation_type = rec.recommendation_type
            rec_row.action = rec.action
            rec_row.reasoning = rec.reasoning
            rec_row.inputs_summary = inputs_summary

        # Update VerificationReport with recommendation FK
        vr = db.execute(
            select(VerificationReport).where(
                VerificationReport.run_record_id == run.id
            )
        ).scalar_one_or_none()
        if vr is not None:
            vr.recommendation_id = rec_row.id

        emit_event_sync(
            db,
            event_type=SignalEvents.recommendation_produced.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "recommendation_type": rec.recommendation_type,
                "action": rec.action,
            },
        )

        # Phase 5: in autonomous mode, route to loop_decide instead of reporting
        from libs.storage.models.research import ResearchCycle

        cycle = db.get(ResearchCycle, run.cycle_id)
        autonomy_cfg = ((cycle.config if cycle else None) or {}).get("autonomy", {})
        is_autonomous = autonomy_cfg.get("mode") == "autonomous"

        if is_autonomous:
            target_status = CycleStatus.loop_deciding.value
            from libs.core.services.job_service import create_job

            create_job(
                db,
                cycle_id=run.cycle_id,
                job_type="loop_decide",
                payload={
                    "run_record_id": str(run.id),
                    "recommendation_id": str(rec_row.id),
                },
                priority=5,
            )
        else:
            target_status = CycleStatus.reporting.value

        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Recommendation: {rec.recommendation_type} — {rec.action[:80]}",
        state_patch={"cycle_status": target_status},
    )
