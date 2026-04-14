"""Repetition detection for the autonomous loop.

Detects exact-duplicate and near-duplicate experiment specs to prevent
the loop from running the same experiment repeatedly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models.experiment import ExperimentSpec


@dataclass(frozen=True)
class RepetitionResult:
    """Result of repetition check."""

    is_duplicate: bool
    is_near_duplicate: bool
    prior_spec_id: UUID | None = None
    match_type: str | None = None  # "exact" | "near_duplicate" | None


def fingerprint_spec(spec: ExperimentSpec) -> str:
    """Compute a stable SHA-256 fingerprint of the meaningful spec fields."""
    payload = _canonicalize({
        "code_plan": spec.code_plan,
        "controls": spec.controls,
        "metrics": spec.metrics,
        "baseline": spec.baseline,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonicalize(obj: Any) -> str:
    """Produce a canonical JSON string: sorted keys, normalized floats."""
    return json.dumps(obj, sort_keys=True, default=_normalize_value)


def _normalize_value(v: Any) -> Any:
    """Normalize values for stable fingerprinting."""
    if isinstance(v, float):
        return round(v, 6)
    return str(v)


def detect_repetition(
    session: Session,
    cycle_id: UUID,
    current_spec: ExperimentSpec,
) -> RepetitionResult:
    """Check if the current spec duplicates or near-duplicates a prior spec in the cycle."""
    from libs.storage.models.experiment import ExperimentSpec as SpecModel

    prior_specs = (
        session.execute(
            select(SpecModel)
            .where(SpecModel.cycle_id == cycle_id)
            .where(SpecModel.id != current_spec.id)
            .where(SpecModel.status == "validated")
        )
        .scalars()
        .all()
    )

    current_fp = fingerprint_spec(current_spec)

    for prior in prior_specs:
        prior_fp = fingerprint_spec(prior)
        if current_fp == prior_fp:
            return RepetitionResult(
                is_duplicate=True,
                is_near_duplicate=False,
                prior_spec_id=prior.id,
                match_type="exact",
            )

    # Near-duplicate check: same code_plan + metrics but controls differ by <= 1%
    current_controls_excluded = _canonicalize({
        "code_plan": current_spec.code_plan,
        "metrics": current_spec.metrics,
        "baseline": current_spec.baseline,
    })

    for prior in prior_specs:
        prior_controls_excluded = _canonicalize({
            "code_plan": prior.code_plan,
            "metrics": prior.metrics,
            "baseline": prior.baseline,
        })
        if (
            current_controls_excluded == prior_controls_excluded
            and _controls_within_tolerance(current_spec.controls, prior.controls)
        ):
                return RepetitionResult(
                    is_duplicate=False,
                    is_near_duplicate=True,
                    prior_spec_id=prior.id,
                    match_type="near_duplicate",
                )

    return RepetitionResult(
        is_duplicate=False,
        is_near_duplicate=False,
    )


def _controls_within_tolerance(
    controls_a: list | None,
    controls_b: list | None,
    tolerance: float = 0.01,
) -> bool:
    """Check if two control lists differ only by numeric values within tolerance."""
    if controls_a is None and controls_b is None:
        return True
    if controls_a is None or controls_b is None:
        return False
    if len(controls_a) != len(controls_b):
        return False

    try:
        str_a = json.dumps(controls_a, sort_keys=True)
        str_b = json.dumps(controls_b, sort_keys=True)
    except (TypeError, ValueError):
        return False

    if str_a == str_b:
        return True

    # Extract all numeric values and check tolerance
    nums_a = _extract_numbers(controls_a)
    nums_b = _extract_numbers(controls_b)

    if len(nums_a) != len(nums_b):
        return False
    if not nums_a:
        # No numeric values and strings differ
        return False

    for a, b in zip(nums_a, nums_b, strict=True):
        if a == 0 and b == 0:
            continue
        denom = max(abs(a), abs(b))
        if denom == 0:
            continue
        if abs(a - b) / denom > tolerance:
            return False

    return True


def _extract_numbers(obj: Any) -> list[float]:
    """Recursively extract all numeric values from a nested structure."""
    result: list[float] = []
    if isinstance(obj, (int, float)):
        result.append(float(obj))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_extract_numbers(item))
    elif isinstance(obj, dict):
        for key in sorted(obj.keys()):
            result.extend(_extract_numbers(obj[key]))
    return result
