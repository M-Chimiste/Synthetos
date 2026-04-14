"""Stable dedupe keys for canonical patterns.

The canonical_patterns table has a unique constraint on (pattern_type, content_key).
Each pattern_type has its own content_key recipe; all recipes are stable hashes
of normalized inputs so re-consolidating the same evidence produces the same key.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

PatternType = str

PATTERN_TYPES: tuple[str, ...] = (
    "failure",
    "remediation",
    "signal_trajectory",
    "successful_line",
    "retrieval_heuristic",
)


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _hash(parts: list[str]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def failure_key(*, failure_class: str, root_cause: str) -> str:
    return _hash([_normalize_text(failure_class), _normalize_text(root_cause)])


def remediation_key(*, failure_class: str, strategy: str, outcome: str) -> str:
    return _hash(
        [
            _normalize_text(failure_class),
            _normalize_text(strategy),
            _normalize_text(outcome),
        ]
    )


def signal_trajectory_key(
    *,
    method_family: str,
    primary_metric_name: str,
    direction_bucket: str,
) -> str:
    return _hash(
        [
            _normalize_text(method_family),
            _normalize_text(primary_metric_name),
            _normalize_text(direction_bucket),
        ]
    )


def successful_line_key(
    *,
    method_family: str,
    primary_metric_name: str,
    problem_domain: str,
) -> str:
    return _hash(
        [
            _normalize_text(method_family),
            _normalize_text(primary_metric_name),
            _normalize_text(problem_domain),
        ]
    )


def retrieval_heuristic_key(
    *, heuristic_kind: str, parameters: dict[str, Any]
) -> str:
    normalized = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return _hash([_normalize_text(heuristic_kind), normalized])


def key_for(pattern_type: PatternType, **kwargs: Any) -> str:
    """Dispatch to the appropriate key function for ``pattern_type``."""
    match pattern_type:
        case "failure":
            return failure_key(**kwargs)
        case "remediation":
            return remediation_key(**kwargs)
        case "signal_trajectory":
            return signal_trajectory_key(**kwargs)
        case "successful_line":
            return successful_line_key(**kwargs)
        case "retrieval_heuristic":
            return retrieval_heuristic_key(**kwargs)
        case _:
            raise ValueError(f"Unknown pattern_type: {pattern_type}")
