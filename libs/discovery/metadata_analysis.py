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
from libs.core.errors import OperationCancelled, OperatorTimeout
from libs.core.logging import get_logger
from libs.core.run_context import check_cancelled
from libs.core.tokens import ContextSection, prompt_budget, trim_to_budget
from libs.prompts import render_prompt
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


def _build_user_prompt(
    *,
    problem_statement: str,
    title: str,
    abstract: str,
    authors: list[str],
    venue: str | None,
    year: int | None,
    budget_tokens: int | None = None,
) -> str:
    author_line = ", ".join(authors[:6]) + ("…" if len(authors) > 6 else "")
    venue_line = venue or "(unknown venue)"
    year_line = str(year) if year else "(unknown year)"
    sections = [
        ContextSection("problem", f"Problem statement:\n{problem_statement}", priority=0),
        ContextSection(
            "paper",
            (
                f"Paper:\nTitle: {title}\n"
                f"Authors: {author_line}\n"
                f"Venue: {venue_line}\n"
                f"Year: {year_line}"
            ),
            priority=0,
        ),
        # HTML-scraped "abstracts" are occasionally whole pages: shrinkable.
        ContextSection("abstract", f"Abstract:\n{abstract}", priority=1, min_chars=400),
        ContextSection("instruction", "Return a structured analysis.", priority=0),
    ]
    if budget_tokens is None:
        return "\n\n".join(s.content for s in sections)
    report = trim_to_budget(sections, budget_tokens)
    if report.trimmed:
        log.info(
            "metadata_analysis.context_trimmed",
            title=title[:80],
            estimated_tokens=report.estimated_tokens,
            truncated=report.truncated,
        )
    return report.text


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
    system_content = render_prompt("discovery.metadata_analysis")
    if skill_prompt:
        system_content = f"{system_content}\n\n{skill_prompt}"
    budget = prompt_budget(
        router.get_role_config(ModelRole.metadata_analysis), system_text=system_content
    )

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
                budget_tokens=budget,
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
            check_cancelled()
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
            except (OperationCancelled, OperatorTimeout):
                raise  # cancellation must abort the whole batch, not one paper
            except Exception as exc:
                log.warning(
                    "metadata_analysis.failed",
                    paper_id=paper.get("id"),
                    error=str(exc),
                )
                return (paper["id"], None, str(exc))

    return await asyncio.gather(*(_do(p) for p in papers))
