"""Metadata-depth LLM analysis for the discovery pipeline.

For each shortlist candidate the system asks a small LLM (the
``metadata_analysis`` role on the model gateway) to read the title and
abstract and return a structured packet describing fit, contribution
type, and escalation rationale.

The packet is stored on ``paper_cards.metadata_analysis`` JSONB column.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from libs.adapters.llm.router import ModelRouter
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole

log = get_logger(__name__)


ContributionType = Literal[
    "benchmark",
    "method",
    "theory",
    "survey",
    "application",
    "artifact",
    "other",
]


class MetadataAnalysisPacket(BaseModel):
    """Structured analysis of one paper's title + abstract."""

    likely_method_family: str = Field(
        description=(
            "Short phrase naming the family of methods used (e.g. 'transformer', 'GAN', 'GP')."
        )
    )
    likely_contribution_type: ContributionType = Field(
        description="What kind of contribution the paper appears to make."
    )
    shortlist_fit: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 probability the paper belongs on the shortlist for this problem.",
    )
    relevance_to_problem: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 estimate of relevance to the user's problem statement.",
    )
    one_line_summary: str = Field(
        description="One-sentence plain summary of the paper.",
    )
    escalation_rationale: str = Field(
        description="Why (or why not) the paper should be escalated to full-text analysis.",
    )
    risks_or_caveats: list[str] = Field(
        default_factory=list,
        description="Notable caveats, limitations, or red flags surfaced from the abstract.",
    )


_SYSTEM_PROMPT = (
    "You are a careful research librarian. Read a paper's title and abstract "
    "and produce a structured analysis. Be conservative: if the abstract is "
    "vague, do not invent claims. Always return the structured fields exactly."
)


def _build_user_prompt(
    *,
    problem_statement: str,
    title: str,
    abstract: str,
    authors: list[str],
    venue: str | None,
    year: int | None,
) -> str:
    author_line = ", ".join(authors[:6]) + ("…" if len(authors) > 6 else "")
    venue_line = venue or "(unknown venue)"
    year_line = str(year) if year else "(unknown year)"
    return (
        f"Problem statement:\n{problem_statement}\n\n"
        f"Paper:\nTitle: {title}\n"
        f"Authors: {author_line}\n"
        f"Venue: {venue_line}\n"
        f"Year: {year_line}\n\n"
        f"Abstract:\n{abstract}\n\n"
        "Return a structured analysis."
    )


async def analyze_one(
    router: ModelRouter,
    *,
    problem_statement: str,
    title: str,
    abstract: str,
    authors: list[str],
    venue: str | None,
    year: int | None,
    skill_prompt: str | None = None,
) -> MetadataAnalysisPacket:
    """Run metadata-depth analysis on a single paper."""
    system_content = _SYSTEM_PROMPT
    if skill_prompt:
        system_content = f"{_SYSTEM_PROMPT}\n\n{skill_prompt}"

    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": _build_user_prompt(
                problem_statement=problem_statement,
                title=title,
                abstract=abstract,
                authors=authors,
                venue=venue,
                year=year,
            ),
        },
    ]
    return await router.complete_structured(
        ModelRole.metadata_analysis,
        messages,
        MetadataAnalysisPacket,
    )


async def analyze_many(
    router: ModelRouter,
    *,
    problem_statement: str,
    papers: list[dict],
    skill_prompt: str | None = None,
    concurrency: int = 4,
) -> list[tuple[str, MetadataAnalysisPacket | None, str | None]]:
    """Run analysis over many papers concurrently with a semaphore.

    Each ``papers`` entry must have ``id``, ``title``, ``abstract``,
    ``authors``, ``venue``, ``year`` keys.

    Returns a list of ``(paper_id, packet, error_message)`` tuples in the
    same order as the input.  ``packet`` is ``None`` when the analysis fails;
    ``error_message`` is non-None in that case.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _do(paper: dict) -> tuple[str, MetadataAnalysisPacket | None, str | None]:
        async with sem:
            try:
                packet = await analyze_one(
                    router,
                    problem_statement=problem_statement,
                    title=paper["title"],
                    abstract=paper["abstract"],
                    authors=paper.get("authors") or [],
                    venue=paper.get("venue"),
                    year=paper.get("year"),
                    skill_prompt=skill_prompt,
                )
                return (paper["id"], packet, None)
            except Exception as exc:
                log.warning(
                    "metadata_analysis.failed",
                    paper_id=paper.get("id"),
                    error=str(exc),
                )
                return (paper["id"], None, str(exc))

    return await asyncio.gather(*(_do(p) for p in papers))
