"""Repetition detection for autonomous experiment loops."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models import ExperimentSpecModel


@dataclass
class RepetitionCheck:
    """Result of checking for experiment repetition."""

    is_repetition: bool
    repetition_type: str | None = None  # "trace_level" | "result_level"
    detail: str | None = None


def compute_spec_hash(spec: ExperimentSpecModel) -> str:
    """Deterministic hash of hypothesis + method + key parameters."""
    key_parts = {
        "hypothesis_card_id": spec.hypothesis_card_id,
        "method_description": spec.method_description or "",
        "metrics": sorted(
            [m.get("name", "") for m in (spec.metrics or [])],
        ),
        "controls": json.dumps(spec.controls or [], sort_keys=True),
        "datasets": json.dumps(spec.datasets or [], sort_keys=True),
    }
    payload = json.dumps(key_parts, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def check_trace_repetition(
    session: Session,
    cycle_id: int,
    hypothesis_id: int,
    spec_hash: str,
) -> RepetitionCheck:
    """Detect if this (hypothesis, spec_hash) has been run before."""
    from libs.storage.models import ExperimentSpecModel, RunRecordModel

    # Find all specs for this hypothesis in this cycle
    specs = list(
        session.scalars(
            select(ExperimentSpecModel).where(
                ExperimentSpecModel.cycle_id == cycle_id,
                ExperimentSpecModel.hypothesis_card_id == hypothesis_id,
            )
        ).all()
    )

    matching_spec_ids = [
        s.id for s in specs if compute_spec_hash(s) == spec_hash
    ]

    if not matching_spec_ids:
        return RepetitionCheck(is_repetition=False)

    # Check if any of these specs have completed runs
    completed_runs = session.scalar(
        select(RunRecordModel.id)
        .where(
            RunRecordModel.cycle_id == cycle_id,
            RunRecordModel.experiment_spec_id.in_(matching_spec_ids),
            RunRecordModel.status.in_(["completed", "succeeded"]),
        )
        .limit(1)
    )

    if completed_runs is not None:
        return RepetitionCheck(
            is_repetition=True,
            repetition_type="trace_level",
            detail=(
                f"Spec hash {spec_hash} already executed for "
                f"hypothesis {hypothesis_id}"
            ),
        )

    return RepetitionCheck(is_repetition=False)


def check_result_repetition(
    session: Session,
    cycle_id: int,
    hypothesis_id: int,
    primary_metric: str,
    recent_n: int = 3,
    noise_threshold_pct: float = 1.0,
) -> RepetitionCheck:
    """Detect if last N runs produced metrics within noise threshold."""
    from libs.storage.models import (
        ExperimentSpecModel,
        RunRecordModel,
    )

    # Get the last N completed runs for this hypothesis
    spec_ids = list(
        session.scalars(
            select(ExperimentSpecModel.id).where(
                ExperimentSpecModel.cycle_id == cycle_id,
                ExperimentSpecModel.hypothesis_card_id == hypothesis_id,
            )
        ).all()
    )

    if not spec_ids:
        return RepetitionCheck(is_repetition=False)

    runs = list(
        session.scalars(
            select(RunRecordModel)
            .where(
                RunRecordModel.cycle_id == cycle_id,
                RunRecordModel.experiment_spec_id.in_(spec_ids),
                RunRecordModel.status.in_(["completed", "succeeded"]),
            )
            .order_by(RunRecordModel.created_at.desc())
            .limit(recent_n)
        ).all()
    )

    if len(runs) < recent_n:
        return RepetitionCheck(is_repetition=False)

    # Extract primary metric values
    values = []
    for run in runs:
        metrics = run.metrics_summary or {}
        if primary_metric in metrics:
            val = metrics[primary_metric]
            if isinstance(val, (int, float)) and val == val:  # skip NaN
                values.append(float(val))

    if len(values) < recent_n:
        return RepetitionCheck(is_repetition=False)

    # Check if all values are within noise threshold of each other
    mean_val = sum(values) / len(values)
    if mean_val == 0:
        return RepetitionCheck(is_repetition=False)

    max_deviation_pct = (
        max(abs(v - mean_val) for v in values) / abs(mean_val) * 100
    )

    if max_deviation_pct <= noise_threshold_pct:
        return RepetitionCheck(
            is_repetition=True,
            repetition_type="result_level",
            detail=(
                f"Last {recent_n} runs for hypothesis {hypothesis_id} "
                f"produced {primary_metric} within "
                f"{max_deviation_pct:.2f}% of each other "
                f"(threshold: {noise_threshold_pct}%)"
            ),
        )

    return RepetitionCheck(is_repetition=False)
