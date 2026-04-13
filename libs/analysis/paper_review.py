"""LLM-driven advisory review artifact generation.

Generates strengths, weaknesses, open questions, and scores for
fully analyzed papers.  Advisory only -- never treated as canonical
evidence source.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.analysis import (
    CoverageDiagnostic,
    PaperAnalysisPacket,
    PaperReviewArtifact,
)

log = get_logger("analysis.paper_review")


class ReviewOutput(BaseModel):
    """Structured output from the review LLM call."""

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    critique: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    reading_priority: str = "medium"


async def generate_review(
    db: Session,
    *,
    packet: PaperAnalysisPacket,
    coverage: CoverageDiagnostic | None,
) -> PaperReviewArtifact:
    """Generate an advisory review artifact for a fully analyzed paper."""
    router = ModelRouter()

    context = _build_review_context(packet, coverage)

    review_output = await router.complete_structured(
        ModelRole.paper_review,
        messages=[
            {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        response_model=ReviewOutput,
    )

    artifact = PaperReviewArtifact(
        id=uuid7(),
        analysis_packet_id=packet.id,
        paper_card_id=packet.paper_card_id,
        strengths=review_output.strengths,
        weaknesses=review_output.weaknesses,
        open_questions=review_output.open_questions,
        critique=review_output.critique,
        scores=review_output.scores,
        reading_priority=review_output.reading_priority,
        created_at=utcnow(),
    )
    db.add(artifact)
    db.flush()

    log.info("review_generated", paper_card_id=str(packet.paper_card_id))
    return artifact


def _build_review_context(
    packet: PaperAnalysisPacket,
    coverage: CoverageDiagnostic | None,
) -> str:
    parts = [
        f"## Paper Summary\n{packet.summary}",
        f"## Key Contributions\n{_format_list(packet.key_contributions)}",
        f"## Methods Used\n{_format_list(packet.methods_used)}",
        f"## Datasets Referenced\n{_format_list(packet.datasets_referenced)}",
    ]

    if packet.reproducibility_notes:
        parts.append(
            f"## Reproducibility Notes\n{_format_dict(packet.reproducibility_notes)}"
        )

    if coverage:
        parts.append(
            f"## Coverage Score\n{coverage.overall_score:.2f}"
        )
        if coverage.warnings:
            parts.append(
                f"## Coverage Warnings\n{chr(10).join(coverage.warnings)}"
            )

    return "\n\n".join(parts)


def _format_list(items: list[Any] | None) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def _format_dict(d: dict | None) -> str:
    if not d:
        return "(none)"
    return "\n".join(f"- {k}: {v}" for k, v in d.items())


_REVIEW_SYSTEM_PROMPT = """\
You are a scientific paper reviewer. Given a structured analysis of a
research paper, provide an advisory review including:

1. **Strengths**: What the paper does well
2. **Weaknesses**: Limitations, methodological concerns, missing comparisons
3. **Open Questions**: Things worth investigating further
4. **Critique**: A brief narrative assessment
5. **Scores**: Rate on these dimensions (0.0-1.0):
   - novelty: How novel are the contributions?
   - rigor: How rigorous is the methodology?
   - relevance: How relevant to the stated problem?
   - clarity: How clear is the presentation?
   - reproducibility: How reproducible are the results?
6. **Reading Priority**: "high", "medium", or "low" based on overall value

Be balanced, specific, and evidence-based. This is advisory, not a
final judgment.
"""
