"""Render the autonomous-loop completion report bundle (markdown + JSON)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

from libs.adapters.llm.router import ModelRouter
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models.autonomy import AutonomyBudget, LoopDecision
    from libs.storage.models.experiment import HypothesisCard
    from libs.storage.models.remediation import MetricFrontier, RunRecommendation

log = get_logger("autonomy.completion_report")


@dataclass
class ReportPaths:
    root: Path
    markdown: Path
    json: Path


def build_report_paths(data_root: Path, cycle_id) -> ReportPaths:
    root = data_root / "reports" / "cycles" / str(cycle_id) / "completion"
    return ReportPaths(root=root, markdown=root / "report.md", json=root / "report.json")


async def _generate_executive_summary(
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    router = ModelRouter()
    try:
        response = await router.complete(
            ModelRole.report_writing,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write concise completion summaries for an autonomous "
                        "ML research loop. Summarize what was explored, where the "
                        "frontier ended, and what should happen next in 3-5 sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode("utf-8"),
                },
            ],
            temperature=0.2,
        )
        return response.content.strip(), router.get_role_config(ModelRole.report_writing)
    finally:
        await router.close()


def _fallback_executive_summary(report_json: dict[str, Any]) -> str:
    final_decision = report_json.get("final_decision", {})
    remediation = report_json.get("remediation", {})
    hypotheses = report_json.get("hypotheses", [])
    guidance = (
        final_decision.get("recommendation_action")
        or final_decision.get("reasoning")
        or "manual review recommended"
    )
    return (
        f"The autonomy loop explored {len(hypotheses)} hypotheses and ended with "
        f"`{final_decision.get('decision', 'unknown')}`. "
        f"Resolved remediation attempts: {remediation.get('resolved', 0)} of "
        f"{remediation.get('total_attempts', 0)}. Next-step guidance: {guidance}"
    )


def generate_executive_summary(
    session: Session,
    *,
    cycle_id,
    report_json: dict[str, Any],
) -> str:
    try:
        content, role_cfg = asyncio.run(_generate_executive_summary(report_json))
        if content:
            record_model_call(
                session,
                cycle_id=cycle_id,
                job_id=None,
                role=ModelRole.report_writing.value,
                provider=str(role_cfg.get("provider", "unknown")),
                model_id=str(role_cfg.get("model", "unknown")),
            )
            return content
    except Exception as exc:  # pragma: no cover - fallback path only
        log.warning("completion_report.summary_failed", cycle_id=str(cycle_id), error=str(exc))

    return _fallback_executive_summary(report_json)


def render_json(
    *,
    cycle_id,
    budget: AutonomyBudget | None,
    decisions: list[LoopDecision],
    cards: list[HypothesisCard],
    frontier_map: dict[str, MetricFrontier],
    remediation_total: int,
    remediation_resolved: int,
    final_recommendation: RunRecommendation | None,
) -> dict[str, Any]:
    frontier_progression = [
        {
            "hypothesis_card_id": card_id,
            "best_metric_value": frontier.best_metric_value,
            "total_runs": frontier.total_runs,
            "successful_runs": frontier.successful_runs,
            "runs_since_improvement": frontier.runs_since_improvement,
            "primary_metric_name": frontier.primary_metric_name,
            "primary_metric_direction": frontier.primary_metric_direction,
        }
        for card_id, frontier in frontier_map.items()
    ]
    final_decision_row = decisions[-1] if decisions else None
    return {
        "cycle_id": str(cycle_id),
        "budget": {
            "total_runs": budget.total_runs if budget else 0,
            "wall_clock_elapsed_s": budget.wall_clock_elapsed_s if budget else 0.0,
            "runs_per_hypothesis": budget.runs_per_hypothesis if budget else {},
        },
        "hypotheses": [
            {
                "card_id": str(card.id),
                "title": card.title,
                "status": card.status,
                "frontier": {
                    "best_metric_value": frontier_map[str(card.id)].best_metric_value,
                    "total_runs": frontier_map[str(card.id)].total_runs,
                    "runs_since_improvement": frontier_map[str(card.id)].runs_since_improvement,
                    "primary_metric_name": frontier_map[str(card.id)].primary_metric_name,
                }
                if str(card.id) in frontier_map
                else None,
            }
            for card in cards
        ],
        "frontier_progression": frontier_progression,
        "decisions": [
            {
                "iteration": row.iteration_number,
                "decision": row.decision,
                "reasoning": row.reasoning,
                "gate_triggered": row.gate_triggered,
                "next_action": row.next_action,
                "hypothesis_card_id": (
                    str(row.hypothesis_card_id)
                    if row.hypothesis_card_id
                    else None
                ),
                "next_hypothesis_card_id": (
                    str(row.next_hypothesis_card_id) if row.next_hypothesis_card_id else None
                ),
                "context_summary_path": row.context_summary_path,
            }
            for row in decisions
        ],
        "remediation": {
            "total_attempts": remediation_total,
            "resolved": remediation_resolved,
        },
        "final_decision": {
            "decision": final_decision_row.decision if final_decision_row else None,
            "reasoning": final_decision_row.reasoning if final_decision_row else None,
            "recommendation_type": (
                final_recommendation.recommendation_type if final_recommendation else None
            ),
            "recommendation_action": final_recommendation.action if final_recommendation else None,
            "recommendation_reasoning": (
                final_recommendation.reasoning if final_recommendation else None
            ),
            "regeneration_suggested": (
                final_decision_row.decision == "stop_exhausted" if final_decision_row else False
            ),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def render_markdown(
    *,
    executive_summary: str,
    report_json: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Autonomous Loop Completion Report",
        "",
        "## Executive Summary",
        "",
        executive_summary,
        "",
        "## Budget Consumption",
        "",
        f"- **Total runs:** {report_json['budget']['total_runs']}",
        (
            f"- **Wall-clock time:** "
            f"{report_json['budget']['wall_clock_elapsed_s'] / 3600.0:.2f} hours"
        ),
        "",
        "## Hypotheses Explored",
        "",
        "| Hypothesis | Status | Best Metric | Runs |",
        "|---|---|---|---|",
    ]
    for row in report_json["hypotheses"]:
        frontier = row["frontier"] or {}
        lines.append(
            f"| {row['title'][:60]} | {row['status']} | "
            f"{frontier.get('best_metric_value', 'N/A')} | "
            f"{frontier.get('total_runs', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Frontier Progression",
            "",
            "| Hypothesis | Metric | Best Value | Successful Runs | Runs Since Improvement |",
            "|---|---|---|---|---|",
        ]
    )
    for row in report_json["frontier_progression"]:
        lines.append(
            f"| {row['hypothesis_card_id'][:8]}… | {row['primary_metric_name']} | "
            f"{row['best_metric_value']} | {row['successful_runs']} | "
            f"{row['runs_since_improvement']} |"
        )
    lines.extend(["", "## Loop Decisions", "", "| # | Decision | Reasoning |", "|---|---|---|"])
    for row in report_json["decisions"]:
        lines.append(f"| {row['iteration']} | {row['decision']} | {row['reasoning'][:120]} |")
    lines.extend(
        [
            "",
            "## Remediation Summary",
            "",
            f"- **Total attempts:** {report_json['remediation']['total_attempts']}",
            f"- **Resolved:** {report_json['remediation']['resolved']}",
            "",
            "## Recommendations",
            "",
            f"- **Final loop decision:** {report_json['final_decision']['decision'] or 'unknown'}",
        ]
    )
    if report_json["final_decision"]["recommendation_type"]:
        lines.append(
            f"- **Recommendation type:** {report_json['final_decision']['recommendation_type']}"
        )
    if report_json["final_decision"]["recommendation_action"]:
        lines.append(
            f"- **Recommended action:** {report_json['final_decision']['recommendation_action']}"
        )
    if report_json["final_decision"]["regeneration_suggested"]:
        lines.append(
            "- **Regeneration guidance:** Consider generating a fresh "
            "hypothesis session before continuing."
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report_bundle(
    paths: ReportPaths,
    *,
    markdown: str,
    json_payload: dict[str, Any],
) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.markdown.write_text(markdown, encoding="utf-8")
    paths.json.write_bytes(orjson.dumps(json_payload, option=orjson.OPT_INDENT_2))
