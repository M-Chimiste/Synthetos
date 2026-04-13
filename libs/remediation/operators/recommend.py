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
    load_run_record,
    run_record_id_from_payload,
)
from libs.remediation.recommendations import RecommendationInputs, compute_recommendation
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import FailurePostmortem, VerificationReport
from libs.storage.models.remediation import (
    DirectionalSignal,
    RemediationAction,
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

        # Count remediation attempts for this spec
        remediation_count = db.execute(
            select(func.count())
            .select_from(RemediationAction)
            .where(RemediationAction.experiment_spec_id == spec.id)
        ).scalar_one()

        # Check if remediation is exhausted (any action with outcome=exhausted)
        remediation_exhausted = db.execute(
            select(RemediationAction)
            .where(
                RemediationAction.experiment_spec_id == spec.id,
                RemediationAction.outcome == "exhausted",
            )
            .limit(1)
        ).scalar_one_or_none() is not None

        # Check for unresolved failures (any postmortem exists for runs of this spec)
        from libs.storage.models.experiment import RunRecord

        has_unresolved = db.execute(
            select(FailurePostmortem)
            .join(RunRecord, FailurePostmortem.run_record_id == RunRecord.id)
            .where(RunRecord.experiment_spec_id == spec.id)
            .limit(1)
        ).scalar_one_or_none() is not None

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
            "failed_path": is_failed_path,
        }

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
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Recommendation: {rec.recommendation_type} — {rec.action[:80]}",
        state_patch={"cycle_status": CycleStatus.reporting.value},
    )
