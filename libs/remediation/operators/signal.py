"""signal_classify operator -- classifies the directional signal for a
successful run, updates the metric frontier, and enqueues the recommend step.
"""

from __future__ import annotations

from sqlalchemy import select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import SignalEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.remediation.frontier import upsert_frontier
from libs.remediation.operators._common import (
    ExecutionStateError,
    enqueue_next_phase4,
    get_primary_metric,
    load_experiment_spec,
    load_run_record,
    run_record_id_from_payload,
)
from libs.remediation.signal_classification import classify_signal
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import (
    ExperimentSpec,
    HypothesisCard,
    RunRecord,
    VerificationReport,
)
from libs.storage.models.remediation import DirectionalSignal

log = get_logger("remediation.signal")


def signal_classify_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = load_experiment_spec(db, run.experiment_spec_id)

        primary = get_primary_metric(spec)
        if primary is None:
            # No metrics to classify -- skip directly to recommend
            enqueue_next_phase4(
                db,
                cycle_id=run.cycle_id,
                next_job_type="recommend",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary="No metrics defined in spec; skipped signal classification.",
            )

        metric_name = str(primary.get("name", ""))
        metric_direction = str(primary.get("direction", "maximize"))

        # Get current value from run metrics
        run_metrics = run.metrics_output or {}
        current_value = run_metrics.get(metric_name)
        if current_value is None:
            enqueue_next_phase4(
                db,
                cycle_id=run.cycle_id,
                next_job_type="recommend",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Primary metric '{metric_name}' not found in run output; skipped.",
            )

        current_value = float(current_value)

        # Load hypothesis card to get hypothesis_card_id for frontier
        hypothesis_card = db.get(HypothesisCard, spec.hypothesis_card_id)
        if hypothesis_card is None:
            enqueue_next_phase4(
                db,
                cycle_id=run.cycle_id,
                next_job_type="recommend",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary="Hypothesis card not found; skipped signal classification.",
            )

        # Build history: all completed runs for this hypothesis line
        # (across all specs linked to the same hypothesis card)
        spec_ids_for_line = db.execute(
            select(ExperimentSpec.id).where(
                ExperimentSpec.hypothesis_card_id == spec.hypothesis_card_id,
            )
        ).scalars().all()

        prior_runs = db.execute(
            select(RunRecord)
            .where(
                RunRecord.experiment_spec_id.in_(spec_ids_for_line),
                RunRecord.id != run.id,
                RunRecord.status == "completed",
            )
            .order_by(RunRecord.completed_at.asc())
        ).scalars().all()

        history_values: list[float] = []
        history_window: list[dict] = []
        for pr in prior_runs:
            pr_metrics = pr.metrics_output or {}
            val = pr_metrics.get(metric_name)
            if val is not None:
                history_values.append(float(val))
                history_window.append({
                    "run_id": str(pr.id),
                    "value": float(val),
                    "created_at": pr.completed_at.isoformat() if pr.completed_at else None,
                })

        # Classify signal
        sig_result = classify_signal(
            current_value=current_value,
            history=history_values,
            direction=metric_direction,
        )

        # Build constraint metrics
        all_metrics = spec.metrics or []
        primary_idx = spec.primary_metric_index or 0
        constraint_metrics = []
        for i, m in enumerate(all_metrics):
            if i == primary_idx:
                continue
            m_name = str(m.get("name", ""))
            m_val = run_metrics.get(m_name)
            if m_val is None:
                continue
            m_min = m.get("min")
            m_max = m.get("max")
            within = True
            if m_min is not None and float(m_val) < float(m_min):
                within = False
            if m_max is not None and float(m_val) > float(m_max):
                within = False
            constraint_metrics.append({
                "name": m_name,
                "value": float(m_val),
                "within_bounds": within,
            })

        # Persist DirectionalSignal
        signal_row = DirectionalSignal(
            id=uuid7(),
            run_record_id=run.id,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            experiment_spec_id=run.experiment_spec_id,
            signal=sig_result.signal,
            primary_metric_name=metric_name,
            primary_metric_value=current_value,
            primary_metric_delta=sig_result.delta,
            primary_metric_direction=metric_direction,
            constraint_metrics=constraint_metrics or None,
            history_window=history_window or None,
            reasoning=sig_result.reasoning,
            created_at=utcnow(),
        )
        db.add(signal_row)

        # Update VerificationReport with signal FK
        vr = db.execute(
            select(VerificationReport).where(
                VerificationReport.run_record_id == run.id
            )
        ).scalar_one_or_none()
        if vr is not None:
            vr.directional_signal_id = signal_row.id

        # Upsert MetricFrontier
        frontier, improved = upsert_frontier(
            db,
            charter_id=run.charter_id,
            hypothesis_card_id=spec.hypothesis_card_id,
            experiment_spec_id=run.experiment_spec_id,
            run_id=run.id,
            metric_name=metric_name,
            metric_direction=metric_direction,
            metric_value=current_value,
            is_successful=True,
        )

        # Emit events
        emit_event_sync(
            db,
            event_type=SignalEvents.signal_classified.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "signal": sig_result.signal,
                "metric_name": metric_name,
                "metric_value": current_value,
                "delta": sig_result.delta,
            },
        )

        frontier_event = (
            SignalEvents.frontier_created if improved and frontier.total_runs == 1
            else SignalEvents.frontier_updated
        )
        emit_event_sync(
            db,
            event_type=frontier_event.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "hypothesis_card_id": str(spec.hypothesis_card_id),
                "best_metric_value": frontier.best_metric_value,
                "runs_since_improvement": frontier.runs_since_improvement,
                "improved": improved,
            },
        )

        # Enqueue recommend
        enqueue_next_phase4(
            db,
            cycle_id=run.cycle_id,
            next_job_type="recommend",
            run_record_id=run.id,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=(
            f"Signal: {sig_result.signal} for {metric_name}={current_value:.4f} "
            f"(delta={sig_result.delta:+.4f}); "
            f"frontier {'improved' if improved else 'unchanged'}"
            if sig_result.delta is not None
            else f"Signal: {sig_result.signal} (first run)"
        ),
    )
