"""Historical comparison queries for verification."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.storage.models import (
    ExperimentSpecModel,
    FailurePostmortemModel,
    ResearchCycleModel,
    RunRecordModel,
    VerificationReportModel,
)


def find_comparable_runs(
    session: Session,
    current_run: RunRecordModel,
    experiment_spec: ExperimentSpecModel,
    *,
    charter_id: int,
) -> list[RunRecordModel]:
    """Find prior completed runs for the same charter.

    Excludes the current run. Returns runs ordered by most recent first.
    """
    stmt = (
        select(RunRecordModel)
        .join(ResearchCycleModel, RunRecordModel.cycle_id == ResearchCycleModel.id)
        .where(
            RunRecordModel.id != current_run.id,
            RunRecordModel.status.in_(("succeeded", "failed")),
            ResearchCycleModel.charter_id == charter_id,
            RunRecordModel.created_at < current_run.created_at,
        )
        .where(
            (RunRecordModel.experiment_spec_id == experiment_spec.id)
            | (
                RunRecordModel.experiment_spec_id.in_(
                    select(ExperimentSpecModel.id).where(
                        ExperimentSpecModel.hypothesis_card_id
                        == experiment_spec.hypothesis_card_id
                    )
                )
            )
            | (
                RunRecordModel.experiment_spec_id.in_(
                    select(ExperimentSpecModel.id).where(
                        sa_func.lower(ExperimentSpecModel.title)
                        == (experiment_spec.title or "").strip().lower()
                    )
                )
            )
        )
        .order_by(RunRecordModel.created_at.desc())
        .limit(20)
    )
    return list(session.scalars(stmt).all())


def compare_to_historical(
    current_metrics: dict[str, Any],
    prior_runs: list[RunRecordModel],
    declared_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare current run metrics against prior runs.

    Returns list of ``{prior_run_public_id, metric, prior_value, current_value, delta}``.
    """
    metric_names = [m.get("name") for m in declared_metrics if m.get("name")]
    if not metric_names:
        # Fall back to all numeric keys in current_metrics
        metric_names = [
            k for k, v in current_metrics.items() if isinstance(v, (int, float))
        ]

    comparisons: list[dict[str, Any]] = []
    for prior in prior_runs:
        prior_metrics = prior.metrics_summary or {}
        for name in metric_names:
            current_val = current_metrics.get(name)
            prior_val = prior_metrics.get(name)
            if current_val is None or prior_val is None:
                continue
            if not isinstance(current_val, (int, float)) or not isinstance(
                prior_val, (int, float)
            ):
                continue
            comparisons.append({
                "prior_run_public_id": prior.public_id,
                "metric": name,
                "prior_value": prior_val,
                "current_value": current_val,
                "delta": round(current_val - prior_val, 6),
            })

    return comparisons


def collect_historical_memory_refs(
    session: Session,
    prior_runs: list[RunRecordModel],
) -> list[dict[str, Any]]:
    """Collect related verification and postmortem memory for prior runs."""
    if not prior_runs:
        return []

    run_ids = [run.id for run in prior_runs]
    verification_reports = {
        item.run_record_id: item
        for item in session.scalars(
            select(VerificationReportModel).where(
                VerificationReportModel.run_record_id.in_(run_ids)
            )
        ).all()
    }
    postmortems = {
        item.run_record_id: item
        for item in session.scalars(
            select(FailurePostmortemModel).where(
                FailurePostmortemModel.run_record_id.in_(run_ids)
            )
        ).all()
    }

    refs: list[dict[str, Any]] = []
    for run in prior_runs:
        vr = verification_reports.get(run.id)
        pm = postmortems.get(run.id)
        if vr is None and pm is None:
            continue
        refs.append({
            "prior_run_public_id": run.public_id,
            "verification_report_public_id": vr.public_id if vr else None,
            "verification_outcome": vr.outcome if vr else run.verification_outcome,
            "verification_summary": vr.reviewer_summary if vr else None,
            "postmortem_public_id": pm.public_id if pm else None,
            "failure_class": pm.failure_class if pm else run.failure_classification,
            "root_cause_summary": pm.root_cause_summary if pm else None,
        })
    return refs


def find_similar_postmortems(
    session: Session,
    failure_class: str,
    *,
    charter_id: int,
    exclude_run_record_id: int | None = None,
) -> list[FailurePostmortemModel]:
    """Find prior postmortems with the same failure class for the same charter."""
    stmt = (
        select(FailurePostmortemModel)
        .join(ResearchCycleModel, FailurePostmortemModel.cycle_id == ResearchCycleModel.id)
        .where(
            FailurePostmortemModel.failure_class == failure_class,
            ResearchCycleModel.charter_id == charter_id,
        )
        .order_by(FailurePostmortemModel.created_at.desc())
        .limit(10)
    )
    if exclude_run_record_id is not None:
        stmt = stmt.where(FailurePostmortemModel.run_record_id != exclude_run_record_id)
    return list(session.scalars(stmt).all())
