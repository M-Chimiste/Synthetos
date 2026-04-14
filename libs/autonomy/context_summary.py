"""Context summarization for long-running autonomous loops.

Generates periodic summaries of loop progress to feed into the protocol
compiler's variation prompts, preventing the LLM from losing track of
what has been tried.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select

from libs.adapters.llm.router import ModelRouter
from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call
from libs.storage.models.autonomy import LoopDecision
from libs.storage.models.experiment import HypothesisCard, RunRecord
from libs.storage.models.remediation import (
    MetricFrontier,
    RemediationAction,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = get_logger("autonomy.context_summary")


@dataclass
class LoopContextSummary:
    """Structured summary of loop progress at a given iteration."""

    cycle_id: str
    iteration_number: int
    hypotheses_tried: list[dict[str, Any]] = field(default_factory=list)
    frontier_progression: list[dict[str, Any]] = field(default_factory=list)
    failure_patterns: dict[str, int] = field(default_factory=dict)
    remediation_summary: dict[str, int] = field(default_factory=dict)
    repeated_approaches: list[str] = field(default_factory=list)
    key_findings: str = ""


def should_generate_summary(total_runs: int, summary_interval: int) -> bool:
    """Check if a summary should be generated at this iteration."""
    if summary_interval <= 0:
        return False
    return total_runs > 0 and total_runs % summary_interval == 0


def generate_summary(
    session: Session,
    cycle_id: UUID,
    charter_id: UUID,
    iteration_number: int,
) -> LoopContextSummary:
    """Generate a structured context summary for the loop so far."""
    summary = LoopContextSummary(
        cycle_id=str(cycle_id),
        iteration_number=iteration_number,
    )

    # Hypotheses tried
    cards = (
        session.execute(
            select(HypothesisCard)
            .where(HypothesisCard.cycle_id == cycle_id)
            .where(
                HypothesisCard.status.in_(
                    ["active", "promising", "stalled", "deprioritized", "validated"]
                )
            )
        )
        .scalars()
        .all()
    )

    for card in cards:
        frontier = session.execute(
            select(MetricFrontier).where(
                MetricFrontier.charter_id == charter_id,
                MetricFrontier.hypothesis_card_id == card.id,
            )
        ).scalar_one_or_none()

        summary.hypotheses_tried.append({
            "card_id": str(card.id),
            "title": card.title,
            "status": card.status,
            "total_runs": frontier.total_runs if frontier else 0,
            "best_metric": frontier.best_metric_value if frontier else None,
            "runs_since_improvement": (
                frontier.runs_since_improvement if frontier else 0
            ),
        })

    # Frontier progression
    frontiers = (
        session.execute(
            select(MetricFrontier).where(MetricFrontier.charter_id == charter_id)
        )
        .scalars()
        .all()
    )
    for f in frontiers:
        summary.frontier_progression.append({
            "hypothesis_card_id": str(f.hypothesis_card_id),
            "best_metric_value": f.best_metric_value,
            "total_runs": f.total_runs,
            "successful_runs": f.successful_runs,
            "runs_since_improvement": f.runs_since_improvement,
        })

    # Failure patterns
    failure_counts = (
        session.execute(
            select(RunRecord.failure_class, func.count())
            .where(RunRecord.cycle_id == cycle_id)
            .where(RunRecord.failure_class.isnot(None))
            .group_by(RunRecord.failure_class)
        )
        .all()
    )
    summary.failure_patterns = {fc: count for fc, count in failure_counts if fc}

    # Remediation summary
    total_attempts = session.execute(
        select(func.count())
        .select_from(RemediationAction)
        .where(RemediationAction.cycle_id == cycle_id)
    ).scalar_one()
    resolved = session.execute(
        select(func.count())
        .select_from(RemediationAction)
        .where(RemediationAction.cycle_id == cycle_id)
        .where(RemediationAction.outcome == "retry_created")
    ).scalar_one()
    exhausted = session.execute(
        select(func.count())
        .select_from(RemediationAction)
        .where(RemediationAction.cycle_id == cycle_id)
        .where(RemediationAction.outcome == "exhausted")
    ).scalar_one()
    summary.remediation_summary = {
        "total_attempts": total_attempts,
        "resolved": resolved,
        "exhausted": exhausted,
    }

    # Loop decisions for repeated approaches
    decisions = (
        session.execute(
            select(LoopDecision)
            .where(LoopDecision.cycle_id == cycle_id)
            .order_by(LoopDecision.iteration_number)
        )
        .scalars()
        .all()
    )
    vary_count = sum(1 for d in decisions if d.decision == "vary_parameters")
    if vary_count >= 3:
        summary.repeated_approaches.append(
            f"Parameter variation attempted {vary_count} times across the loop."
        )

    summary.key_findings = _generate_key_findings(session, summary)
    return summary


def write_summary(
    summary: LoopContextSummary,
    cycle_id: UUID,
) -> str:
    """Write summary to disk and return the file path."""
    settings = get_settings()
    summary_dir = (
        settings.data_root / "reports" / "cycles" / str(cycle_id) / "summaries"
    )
    summary_dir.mkdir(parents=True, exist_ok=True)

    filename = f"summary_{summary.iteration_number}.json"
    path = summary_dir / filename
    path.write_text(
        json.dumps(asdict(summary), indent=2, default=str),
        encoding="utf-8",
    )

    log.info(
        "context_summary_written",
        cycle_id=str(cycle_id),
        iteration=summary.iteration_number,
        path=str(path),
    )
    return str(path)


async def _summarize_with_model(summary: LoopContextSummary) -> tuple[str, dict[str, Any]]:
    router = ModelRouter()
    try:
        system = (
            "You summarize the progress of an autonomous ML research loop. "
            "Write 2-3 concise sentences that capture what has been tried, "
            "where the frontier stands, and what the loop should avoid repeating."
        )
        user = json.dumps(
            {
                "iteration_number": summary.iteration_number,
                "hypotheses_tried": summary.hypotheses_tried,
                "frontier_progression": summary.frontier_progression,
                "failure_patterns": summary.failure_patterns,
                "remediation_summary": summary.remediation_summary,
                "repeated_approaches": summary.repeated_approaches,
            },
            indent=2,
            default=str,
        )
        response = await router.complete(
            ModelRole.summarization,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return response.content.strip(), router.get_role_config(ModelRole.summarization)
    finally:
        await router.close()


def _fallback_findings(summary: LoopContextSummary) -> str:
    hypothesis_count = len(summary.hypotheses_tried)
    repeated = (
        summary.repeated_approaches[0]
        if summary.repeated_approaches
        else "No repeated approaches detected yet."
    )
    frontier_values = [
        float(value)
        for row in summary.frontier_progression
        for value in [row.get("best_metric_value")]
        if value is not None
    ]
    best_frontier = max(frontier_values, default=None)
    frontier_text = (
        f"Best recorded frontier value is {best_frontier}."
        if best_frontier is not None
        else "No frontier improvement has been recorded yet."
    )
    return (
        f"The loop has explored {hypothesis_count} hypotheses so far. "
        f"{frontier_text} {repeated}"
    )


def _generate_key_findings(session: Session, summary: LoopContextSummary) -> str:
    try:
        content, role_cfg = asyncio.run(_summarize_with_model(summary))
        if content:
            record_model_call(
                session,
                cycle_id=UUID(summary.cycle_id),
                job_id=None,
                role=ModelRole.summarization.value,
                provider=str(role_cfg.get("provider", "unknown")),
                model_id=str(role_cfg.get("model", "unknown")),
            )
            return content
    except Exception as exc:  # pragma: no cover - exercised via fallback path
        log.warning("context_summary.model_failed", cycle_id=summary.cycle_id, error=str(exc))

    return _fallback_findings(summary)
