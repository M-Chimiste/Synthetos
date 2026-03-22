"""Phase 2 business logic: evidence extraction, hypothesis portfolio, protocol compilation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.ids import generate_public_id
from libs.storage.models import (
    EvidenceCardModel,
    ExperimentSpecModel,
    HypothesisCardModel,
    PaperCardModel,
)

# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def get_papers_for_evidence_extraction(
    session: Session, cycle_id: int,
) -> list[PaperCardModel]:
    """Shortlisted/escalated papers that don't yet have evidence cards."""
    papers_with_evidence = (
        select(EvidenceCardModel.paper_card_id)
        .where(EvidenceCardModel.cycle_id == cycle_id)
        .distinct()
    )
    return list(
        session.scalars(
            select(PaperCardModel)
            .where(
                PaperCardModel.cycle_id == cycle_id,
                PaperCardModel.lifecycle_status.in_([
                    "shortlisted", "html_fetched", "pdf_fetched",
                ]),
                PaperCardModel.id.not_in(papers_with_evidence),
            )
            .order_by(PaperCardModel.shortlist_rank.asc())
        ).all()
    )


def create_evidence_card(
    session: Session,
    cycle_id: int,
    paper_card_id: int,
    *,
    claim: str,
    evidence_type: str,
    strength: str,
    relevance_score: float,
    relevance_rationale: str,
    source_section: str | None,
    source_quote: str | None,
    read_depth: str,
    model_route_id: str,
    prompt_id: str,
) -> EvidenceCardModel:
    """Persist one evidence card."""
    card = EvidenceCardModel(
        public_id=generate_public_id("evidence"),
        cycle_id=cycle_id,
        paper_card_id=paper_card_id,
        claim=claim,
        evidence_type=evidence_type,
        strength=strength,
        relevance_score=relevance_score,
        relevance_rationale=relevance_rationale,
        source_section=source_section,
        source_quote=source_quote,
        read_depth=read_depth,
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )
    session.add(card)
    session.flush()
    return card


def detect_conflicts_and_redundancy(
    session: Session, cycle_id: int,
) -> tuple[int, int]:
    """Simple pairwise comparison of evidence claims by exact substring overlap.

    Returns (conflict_count, redundancy_count).
    """
    cards = list(
        session.scalars(
            select(EvidenceCardModel)
            .where(EvidenceCardModel.cycle_id == cycle_id)
            .order_by(EvidenceCardModel.id)
        ).all()
    )
    conflict_count = 0
    redundancy_count = 0

    for i, a in enumerate(cards):
        for b in cards[i + 1 :]:
            claim_a = a.claim.lower().strip()
            claim_b = b.claim.lower().strip()
            # Very simple heuristic: high overlap → redundant
            if claim_a == claim_b or (
                len(claim_a) > 20 and len(claim_b) > 20 and (
                    claim_a in claim_b or claim_b in claim_a
                )
            ):
                if b.public_id not in (a.redundant_with or []):
                    a.redundant_with = list(a.redundant_with or []) + [b.public_id]
                    b.redundant_with = list(b.redundant_with or []) + [a.public_id]
                    redundancy_count += 1

    session.flush()
    return conflict_count, redundancy_count


def list_evidence_for_cycle(
    session: Session, cycle_id: int, type_filter: str | None = None,
) -> list[EvidenceCardModel]:
    stmt = select(EvidenceCardModel).where(EvidenceCardModel.cycle_id == cycle_id)
    if type_filter:
        stmt = stmt.where(EvidenceCardModel.evidence_type == type_filter)
    stmt = stmt.order_by(EvidenceCardModel.relevance_score.desc())
    return list(session.scalars(stmt).all())


def build_evidence_summary(session: Session, cycle_id: int) -> dict[str, Any]:
    """Aggregate counts by type, strength, conflicts, redundancies."""
    cards = list_evidence_for_cycle(session, cycle_id)
    by_type: dict[str, int] = {}
    by_strength: dict[str, int] = {}
    conflicts = 0
    redundancies = 0
    for c in cards:
        by_type[c.evidence_type] = by_type.get(c.evidence_type, 0) + 1
        by_strength[c.strength] = by_strength.get(c.strength, 0) + 1
        conflicts += len(c.conflict_with or [])
        redundancies += len(c.redundant_with or [])
    return {
        "total_evidence": len(cards),
        "by_type": by_type,
        "by_strength": by_strength,
        "conflicts_detected": conflicts // 2,  # each pair counted twice
        "redundancies_detected": redundancies // 2,
    }


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------


def create_hypothesis_card(
    session: Session,
    cycle_id: int,
    *,
    title: str,
    statement: str,
    rationale: str,
    approach_summary: str,
    supporting_evidence: list[str],
    counter_evidence: list[str],
    model_route_id: str,
    prompt_id: str,
) -> HypothesisCardModel:
    card = HypothesisCardModel(
        public_id=generate_public_id("hyp"),
        cycle_id=cycle_id,
        title=title,
        statement=statement,
        rationale=rationale,
        approach_summary=approach_summary,
        supporting_evidence=supporting_evidence,
        counter_evidence=counter_evidence,
        status="generated",
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )
    session.add(card)
    session.flush()
    return card


def record_hypothesis_critique(
    session: Session,
    hypothesis: HypothesisCardModel,
    critique_data: dict[str, Any],
) -> None:
    """Apply critique results to a hypothesis card."""
    hypothesis.novelty_score = critique_data.get("novelty_score")
    hypothesis.feasibility_score = critique_data.get("feasibility_score")
    hypothesis.impact_score = critique_data.get("impact_score")
    hypothesis.critique_summary = critique_data.get("critique_summary")
    hypothesis.critique_issues = critique_data.get("issues", [])
    hypothesis.status = "critiqued"
    session.flush()


def compute_portfolio_ranking(
    session: Session,
    cycle_id: int,
    auto_approve_top_n: int = 3,
) -> list[HypothesisCardModel]:
    """Rank hypotheses by composite score = novelty * feasibility * impact.

    Auto-approve top N hypotheses (status → 'approved').
    """
    hypotheses = list(
        session.scalars(
            select(HypothesisCardModel).where(
                HypothesisCardModel.cycle_id == cycle_id,
                HypothesisCardModel.status.in_(["critiqued", "generated"]),
            )
        ).all()
    )

    for h in hypotheses:
        n = h.novelty_score or 0.0
        f = h.feasibility_score or 0.0
        i = h.impact_score or 0.0
        h.portfolio_score = round(n * f * i, 6)

    hypotheses.sort(key=lambda h: h.portfolio_score or 0.0, reverse=True)

    for rank, h in enumerate(hypotheses, start=1):
        h.portfolio_rank = rank
        h.ranking_rationale = (
            f"Composite score {h.portfolio_score:.4f} "
            f"(novelty={h.novelty_score}, feasibility={h.feasibility_score}, "
            f"impact={h.impact_score})"
        )
        if rank <= auto_approve_top_n:
            h.status = "approved"

    session.flush()
    return hypotheses


def get_approved_hypotheses(
    session: Session, cycle_id: int,
) -> list[HypothesisCardModel]:
    return list(
        session.scalars(
            select(HypothesisCardModel).where(
                HypothesisCardModel.cycle_id == cycle_id,
                HypothesisCardModel.status == "approved",
            ).order_by(HypothesisCardModel.portfolio_rank.asc())
        ).all()
    )


# ---------------------------------------------------------------------------
# Protocol / ExperimentSpec
# ---------------------------------------------------------------------------


def create_experiment_spec(
    session: Session,
    cycle_id: int,
    hypothesis_card_id: int,
    *,
    spec_data: dict[str, Any],
    model_route_id: str,
    prompt_id: str,
) -> ExperimentSpecModel:
    spec = ExperimentSpecModel(
        public_id=generate_public_id("expspec"),
        cycle_id=cycle_id,
        hypothesis_card_id=hypothesis_card_id,
        title=spec_data.get("title", "Untitled Experiment"),
        objective=spec_data.get("objective", ""),
        baseline_description=spec_data.get("baseline_description", ""),
        method_description=spec_data.get("method_description", ""),
        controls=spec_data.get("controls", []),
        metrics=spec_data.get("metrics", []),
        datasets=spec_data.get("datasets", []),
        artifacts=spec_data.get("artifacts", []),
        stop_conditions=spec_data.get("stop_conditions", []),
        expected_outputs=spec_data.get("expected_outputs", []),
        estimated_runtime_minutes=spec_data.get("estimated_runtime_minutes"),
        gpu_required=spec_data.get("gpu_required", False),
        resource_requirements=spec_data.get("resource_requirements", {}),
        status="draft",
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )
    session.add(spec)
    session.flush()
    return spec


def validate_experiment_spec(spec: ExperimentSpecModel) -> list[dict[str, str]]:
    """Deterministic validation — checks structural completeness.

    Returns list of {field, issue, severity} dicts.
    """
    issues: list[dict[str, str]] = []

    if not spec.metrics:
        issues.append({
            "field": "metrics",
            "issue": "At least one metric is required",
            "severity": "blocking",
        })
    if not spec.datasets:
        issues.append({
            "field": "datasets",
            "issue": "At least one dataset is required",
            "severity": "blocking",
        })
    if not (spec.baseline_description or "").strip():
        issues.append({
            "field": "baseline_description",
            "issue": "Baseline description must not be empty",
            "severity": "blocking",
        })
    if not spec.expected_outputs:
        issues.append({
            "field": "expected_outputs",
            "issue": "At least one expected output is required",
            "severity": "blocking",
        })
    if not (spec.objective or "").strip():
        issues.append({
            "field": "objective",
            "issue": "Objective must not be empty",
            "severity": "warning",
        })
    if not spec.stop_conditions:
        issues.append({
            "field": "stop_conditions",
            "issue": "At least one stop condition is recommended",
            "severity": "warning",
        })

    return issues


def reject_experiment_spec(
    session: Session, spec: ExperimentSpecModel, reason: str,
) -> None:
    spec.status = "rejected"
    spec.rejection_reason = reason
    session.flush()
