"""LLM-assisted multi-metric tradeoff resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import jinja2

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "verification" / "v1"
_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
    undefined=jinja2.StrictUndefined,
)

_ALLOWED_RESOLUTIONS = {
    "accept_tradeoff",
    "reject_tradeoff",
    "needs_investigation",
}


def resolve_metric_tradeoff(
    *,
    gateway: Any,
    charter_problem: str,
    experiment_title: str,
    primary_metric: str,
    primary_value: float | None,
    primary_signal: str,
    primary_higher_is_better: bool,
    conflicts: list[dict[str, Any]],
    metric_histories: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Ask the verifier model to judge whether a metric tradeoff is acceptable."""
    if not conflicts:
        return {
            "resolution": "accept_tradeoff",
            "rationale": "No conflicting constraint metrics were detected.",
            "recommendation": "Continue monitoring the constraint metrics.",
            "resolved_by": "deterministic",
        }

    try:
        template = _JINJA_ENV.get_template("metric_conflict_resolution.md")
        rendered = template.render(
            charter_problem=charter_problem,
            experiment_title=experiment_title,
            primary_metric=primary_metric,
            primary_value=primary_value,
            primary_signal=primary_signal,
            primary_higher_is_better=primary_higher_is_better,
            conflicts=conflicts,
            metric_histories=metric_histories,
        )
        response = gateway.call_structured(
            "verifier",
            [{"role": "user", "content": rendered}],
            temperature=0.2,
            max_tokens=384,
        )
        resolution = str(response.get("resolution", "needs_investigation")).lower()
        if resolution not in _ALLOWED_RESOLUTIONS:
            resolution = "needs_investigation"
        return {
            "resolution": resolution,
            "rationale": str(response.get("rationale", "")).strip(),
            "recommendation": str(response.get("recommendation", "")).strip(),
            "resolved_by": "verifier_llm",
        }
    except Exception:
        log.warning("metric_tradeoff_resolution_failed", exc_info=True)
        return {
            "resolution": "needs_investigation",
            "rationale": (
                "Constraint conflicts were detected, but the verifier could not complete "
                "a tradeoff judgment."
            ),
            "recommendation": "Run a follow-up experiment focused on the conflicting metrics.",
            "resolved_by": "fallback",
        }
