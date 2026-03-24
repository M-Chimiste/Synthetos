"""Helpers for preserving autonomous loop context across operator hops."""

from __future__ import annotations

from typing import Any

AUTONOMOUS_PAYLOAD_DEFAULTS: dict[str, Any] = {
    "autonomous_loop_iteration": 1,
    "selected_hypothesis_public_id": None,
    "last_hypothesis_public_id": None,
    "last_run_public_id": None,
    "regeneration_attempted": False,
    "autonomous_regeneration": False,
    "parameter_variation_hints": [],
    "variation_mode": False,
}

AUTONOMOUS_PAYLOAD_KEYS = frozenset(AUTONOMOUS_PAYLOAD_DEFAULTS.keys())


def normalize_autonomous_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a stable autonomous payload shape.

    Older payloads used `iteration` / `loop_iteration`; keep accepting those while
    writing back the canonical `autonomous_loop_iteration` key.
    """

    normalized = dict(payload or {})
    iteration = normalized.get("autonomous_loop_iteration")
    if iteration is None:
        iteration = normalized.get("iteration")
    if iteration is None:
        iteration = normalized.get("loop_iteration")
    if iteration is None:
        iteration = AUTONOMOUS_PAYLOAD_DEFAULTS["autonomous_loop_iteration"]
    normalized["autonomous_loop_iteration"] = int(iteration)
    normalized.pop("iteration", None)
    normalized.pop("loop_iteration", None)

    for key, default in AUTONOMOUS_PAYLOAD_DEFAULTS.items():
        if key == "autonomous_loop_iteration":
            continue
        if key not in normalized:
            normalized[key] = list(default) if isinstance(default, list) else default
    return normalized


def merge_autonomous_payload(
    payload: dict[str, Any] | None,
    **updates: Any,
) -> dict[str, Any]:
    """Merge updates into an autonomous payload while preserving canonical keys."""

    merged = normalize_autonomous_payload(payload)
    for key, value in updates.items():
        if value is not None or key in AUTONOMOUS_PAYLOAD_KEYS:
            merged[key] = value
    return merged
