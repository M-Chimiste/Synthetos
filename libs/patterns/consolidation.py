"""Consolidation logic for canonical patterns.

Pure, deterministic functions that take raw source-artifact rows and emit
``PatternCandidate`` records keyed by the content-key recipes in
``content_key.py``. The consolidation operator upserts candidates into
``canonical_patterns`` and links observations back to source artifacts.

No LLM calls live here -- these are shaping + aggregation functions so they
stay trivially unit-testable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from libs.patterns import content_key
from libs.storage.models.autonomy import LoopDecision
from libs.storage.models.experiment import FailurePostmortem, HypothesisCard
from libs.storage.models.remediation import (
    DirectionalSignal,
    MetricFrontier,
    RemediationAction,
)

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class PatternCandidate:
    """One pattern candidate derived from a single source artifact."""

    pattern_type: str
    content_key: str
    title: str
    summary: str
    structured_body: dict[str, Any]
    charter_id: UUID
    cycle_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    observed_at: datetime
    contribution: dict[str, Any] | None = None


@dataclass
class AggregatedPattern:
    """Aggregation of multiple candidates sharing the same content key."""

    pattern_type: str
    content_key: str
    title: str
    summary: str
    structured_body: dict[str, Any]
    evidence_count: int
    charter_ids: list[UUID]
    first_observed_at: datetime
    last_observed_at: datetime
    candidates: list[PatternCandidate] = field(default_factory=list)

    @property
    def cross_charter(self) -> bool:
        return len(self.charter_ids) > 1


# ---------------------------------------------------------------------------
# Per-artifact extractors
# ---------------------------------------------------------------------------


def _normalize_root_cause(text: str | None, limit: int = 200) -> str:
    if not text:
        return "unspecified"
    t = " ".join(text.split()).lower()
    return t[:limit]


def extract_failure(pm: FailurePostmortem) -> PatternCandidate:
    root_cause = _normalize_root_cause(pm.root_cause)
    key = content_key.failure_key(failure_class=pm.failure_class, root_cause=root_cause)
    contributing = pm.contributing_factors or []
    summary = pm.root_cause or "No root cause recorded."
    title = f"{pm.failure_class}: {root_cause[:80]}"
    body = {
        "failure_class": pm.failure_class,
        "root_cause_normalized": root_cause,
        "contributing_factors": contributing,
        "lesson_count": len(pm.lessons or []),
    }
    return PatternCandidate(
        pattern_type="failure",
        content_key=key,
        title=title,
        summary=summary,
        structured_body=body,
        charter_id=pm.charter_id,
        cycle_id=pm.cycle_id,
        source_artifact_type="postmortem",
        source_artifact_id=pm.id,
        observed_at=pm.created_at,
        contribution={
            "next_step_recommendation": pm.next_step_recommendation,
        },
    )


def extract_remediation(ra: RemediationAction) -> PatternCandidate:
    key = content_key.remediation_key(
        failure_class=ra.failure_class,
        strategy=ra.strategy,
        outcome=ra.outcome,
    )
    title = f"{ra.failure_class} → {ra.strategy} ({ra.outcome})"
    summary = ra.reasoning or f"{ra.strategy} attempted on {ra.failure_class}."
    body = {
        "failure_class": ra.failure_class,
        "strategy": ra.strategy,
        "strategy_tier": ra.strategy_tier,
        "outcome": ra.outcome,
    }
    return PatternCandidate(
        pattern_type="remediation",
        content_key=key,
        title=title,
        summary=summary,
        structured_body=body,
        charter_id=ra.charter_id,
        cycle_id=ra.cycle_id,
        source_artifact_type="remediation_action",
        source_artifact_id=ra.id,
        observed_at=ra.created_at,
        contribution={
            "attempt_number": ra.attempt_number,
            "action_detail": ra.action_detail,
        },
    )


def _signal_direction_bucket(signal: DirectionalSignal) -> str:
    return f"{signal.primary_metric_direction}_{signal.signal}"


def _method_family_from_hypothesis(h: HypothesisCard | None) -> str:
    if h is None:
        return "unspecified"
    for source in (h.title, h.statement):
        if not source:
            continue
        token = source.strip().split()[0] if source.strip() else ""
        if token:
            return token.lower()
    return "unspecified"


def extract_signal_trajectory(
    signal: DirectionalSignal,
    *,
    hypothesis: HypothesisCard | None = None,
) -> PatternCandidate:
    method_family = _method_family_from_hypothesis(hypothesis)
    direction_bucket = _signal_direction_bucket(signal)
    key = content_key.signal_trajectory_key(
        method_family=method_family,
        primary_metric_name=signal.primary_metric_name,
        direction_bucket=direction_bucket,
    )
    title = (
        f"{method_family} / {signal.primary_metric_name} ({direction_bucket})"
    )
    summary = signal.reasoning or ""
    body = {
        "method_family": method_family,
        "primary_metric_name": signal.primary_metric_name,
        "primary_metric_direction": signal.primary_metric_direction,
        "signal": signal.signal,
        "direction_bucket": direction_bucket,
        "primary_metric_delta": signal.primary_metric_delta,
    }
    return PatternCandidate(
        pattern_type="signal_trajectory",
        content_key=key,
        title=title,
        summary=summary,
        structured_body=body,
        charter_id=signal.charter_id,
        cycle_id=signal.cycle_id,
        source_artifact_type="directional_signal",
        source_artifact_id=signal.id,
        observed_at=signal.created_at,
        contribution={
            "primary_metric_value": signal.primary_metric_value,
        },
    )


def extract_successful_line(
    frontier: MetricFrontier,
    *,
    hypothesis: HypothesisCard | None = None,
    cycle_id: UUID,
    problem_domain: str = "unspecified",
) -> PatternCandidate:
    method_family = _method_family_from_hypothesis(hypothesis)
    key = content_key.successful_line_key(
        method_family=method_family,
        primary_metric_name=frontier.primary_metric_name,
        problem_domain=problem_domain,
    )
    title = (
        f"Successful line: {method_family} / {frontier.primary_metric_name} "
        f"[{problem_domain}]"
    )
    summary = (
        f"best={frontier.best_metric_value} "
        f"runs={frontier.total_runs} successful={frontier.successful_runs}"
    )
    body = {
        "method_family": method_family,
        "primary_metric_name": frontier.primary_metric_name,
        "primary_metric_direction": frontier.primary_metric_direction,
        "best_metric_value": frontier.best_metric_value,
        "problem_domain": problem_domain,
        "total_runs": frontier.total_runs,
        "successful_runs": frontier.successful_runs,
    }
    return PatternCandidate(
        pattern_type="successful_line",
        content_key=key,
        title=title,
        summary=summary,
        structured_body=body,
        charter_id=frontier.charter_id,
        cycle_id=cycle_id,
        source_artifact_type="metric_frontier",
        source_artifact_id=frontier.id,
        observed_at=frontier.best_achieved_at,
    )


def extract_retrieval_heuristic_from_loop(
    decision: LoopDecision,
) -> PatternCandidate | None:
    """Loop decisions marked 'parameter_variation' or 'hypothesis_pivot' can seed
    a retrieval heuristic (what kinds of pivots tend to follow what signals)."""
    if decision.decision not in {"parameter_variation", "hypothesis_pivot"}:
        return None
    heuristic_kind = f"loop_{decision.decision}"
    parameters = {
        "gate_triggered": decision.gate_triggered,
        "next_action": decision.next_action,
    }
    key = content_key.retrieval_heuristic_key(
        heuristic_kind=heuristic_kind, parameters=parameters
    )
    title = f"Loop heuristic: {decision.decision}"
    summary = decision.reasoning or ""
    body = {
        "heuristic_kind": heuristic_kind,
        "parameters": parameters,
    }
    return PatternCandidate(
        pattern_type="retrieval_heuristic",
        content_key=key,
        title=title,
        summary=summary,
        structured_body=body,
        charter_id=decision.charter_id,
        cycle_id=decision.cycle_id,
        source_artifact_type="loop_decision",
        source_artifact_id=decision.id,
        observed_at=decision.created_at,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(candidates: list[PatternCandidate]) -> list[AggregatedPattern]:
    """Group candidates by (pattern_type, content_key) and summarize."""
    groups: dict[tuple[str, str], list[PatternCandidate]] = defaultdict(list)
    for c in candidates:
        groups[(c.pattern_type, c.content_key)].append(c)

    aggregated: list[AggregatedPattern] = []
    for (pattern_type, key), items in groups.items():
        items_sorted = sorted(items, key=lambda c: c.observed_at)
        first = items_sorted[0]
        last = items_sorted[-1]
        charter_ids = list({c.charter_id for c in items})
        # Merge structured bodies: last-writer-wins on scalars, union on list-keys
        merged_body = dict(last.structured_body)
        merged_body["charter_count"] = len(charter_ids)
        aggregated.append(
            AggregatedPattern(
                pattern_type=pattern_type,
                content_key=key,
                title=last.title,
                summary=last.summary,
                structured_body=merged_body,
                evidence_count=len(items),
                charter_ids=charter_ids,
                first_observed_at=first.observed_at,
                last_observed_at=last.observed_at,
                candidates=items,
            )
        )
    return aggregated


def compute_confidence(agg: AggregatedPattern) -> float:
    """Simple evidence-based confidence with cross-charter boost.

    evidence_count=1 -> 0.35
    evidence_count=2 -> 0.55
    evidence_count>=5 -> 0.80 (capped)
    Cross-charter adds +0.10 up to 0.95 cap.
    """
    base = min(0.35 + 0.10 * (agg.evidence_count - 1), 0.80)
    if agg.cross_charter:
        base = min(base + 0.10, 0.95)
    return round(base, 3)
