"""Helpers for loading and applying discovery-phase skills."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.adapters.llm.router import ModelRouter
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.skills import SkillDefinition

if TYPE_CHECKING:
    from libs.storage.models.papers import PaperCard


@dataclass
class SkillPromptResult:
    """Resolved skill prompt text or a non-blocking warning."""

    prompt: str | None
    warning: str | None = None


class ProblemScopingPacket(BaseModel):
    """Structured retrieval-hint artifact produced during intake."""

    dense_query: str = Field(
        description="A concise retrieval-oriented query string for search adapters."
    )
    synonyms: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class ShortlistCritiquePacket(BaseModel):
    """Advisory critique of the stable + discovery shortlist views."""

    summary: str
    coverage_gaps: list[str] = Field(default_factory=list)
    clustering_risks: list[str] = Field(default_factory=list)
    score_concerns: list[str] = Field(default_factory=list)


_PROBLEM_SCOPING_SYSTEM_PROMPT = (
    "You are helping scope a literature search. Produce retrieval hints that "
    "tighten the user's problem statement without changing its intent. Return "
    "only the structured fields."
)

_SHORTLIST_CRITIQUE_SYSTEM_PROMPT = (
    "You are reviewing a metadata-only literature shortlist. Be concise, "
    "practical, and skeptical. Flag coverage gaps, topic clustering, and weak "
    "shortlist evidence without inventing missing facts. Return only the "
    "structured fields."
)


def load_skill_prompt(
    session: Session,
    *,
    skill_id: str,
    operator_type: str,
) -> SkillPromptResult:
    """Load a prompt body from the persisted skill registry."""
    skill = session.execute(
        select(SkillDefinition).where(SkillDefinition.skill_id == skill_id)
    ).scalar_one_or_none()
    if skill is None:
        return SkillPromptResult(prompt=None, warning=f"skill '{skill_id}' not found in registry")
    if not skill.enabled:
        return SkillPromptResult(prompt=None, warning=f"skill '{skill_id}' is disabled")

    manifest = skill.manifest or {}
    allowed_operators = manifest.get("allowed_operators") or []
    if allowed_operators and operator_type not in allowed_operators:
        return SkillPromptResult(
            prompt=None,
            warning=(
                f"skill '{skill_id}' is not allowed for operator '{operator_type}'"
            ),
        )

    body = (skill.body or "").strip()
    if not body:
        return SkillPromptResult(prompt=None, warning=f"skill '{skill_id}' has no prompt body")

    return SkillPromptResult(prompt=body)


def join_skill_prompts(*prompts: str | None) -> str | None:
    """Join several advisory prompts into one block."""
    parts = [prompt.strip() for prompt in prompts if prompt and prompt.strip()]
    if not parts:
        return None
    return "\n\n".join(parts)


async def _scope_problem_async(
    *,
    query_text: str,
    notes: str,
    skill_prompt: str,
) -> ProblemScopingPacket:
    router = ModelRouter()
    try:
        messages = [
            {
                "role": "system",
                "content": f"{_PROBLEM_SCOPING_SYSTEM_PROMPT}\n\n{skill_prompt}",
            },
            {
                "role": "user",
                "content": (
                    f"Problem statement:\n{query_text}\n\n"
                    f"Notes:\n{notes or '(none)'}\n\n"
                    "Return the tightened query, synonyms, likely arXiv categories, "
                    "and obvious exclusions."
                ),
            },
        ]
        return await router.complete_structured(
            ModelRole.planning,
            messages,
            ProblemScopingPacket,
        )
    finally:
        with contextlib.suppress(RuntimeError):
            await router.close()


def run_problem_scoping(
    *,
    query_text: str,
    notes: str,
    skill_prompt: str,
) -> ProblemScopingPacket:
    """Run the intake scoping skill via the planning model role."""
    return asyncio.run(
        _scope_problem_async(
            query_text=query_text,
            notes=notes,
            skill_prompt=skill_prompt,
        )
    )


def _card_for_prompt(card: PaperCard) -> dict[str, object]:
    analysis = card.metadata_analysis or {}
    return {
        "title": card.title,
        "authors": card.authors or [],
        "year": card.year,
        "venue": card.venue,
        "source": card.source,
        "final_score": card.final_score,
        "shortlist_fit": analysis.get("shortlist_fit"),
        "relevance_to_problem": analysis.get("relevance_to_problem"),
        "summary": analysis.get("one_line_summary"),
        "escalation_rationale": analysis.get("escalation_rationale"),
    }


async def _critique_shortlist_async(
    *,
    problem_statement: str,
    stable_view: list[PaperCard],
    discovery_view: list[PaperCard],
    skill_prompt: str,
) -> ShortlistCritiquePacket:
    router = ModelRouter()
    try:
        messages = [
            {
                "role": "system",
                "content": f"{_SHORTLIST_CRITIQUE_SYSTEM_PROMPT}\n\n{skill_prompt}",
            },
            {
                "role": "user",
                "content": (
                    f"Problem statement:\n{problem_statement}\n\n"
                    f"Stable view:\n{_card_list_for_prompt(stable_view)}\n\n"
                    f"Discovery view:\n{_card_list_for_prompt(discovery_view)}\n\n"
                    "Provide a short critique of the combined shortlist."
                ),
            },
        ]
        return await router.complete_structured(
            ModelRole.evaluation,
            messages,
            ShortlistCritiquePacket,
        )
    finally:
        with contextlib.suppress(RuntimeError):
            await router.close()


def _card_list_for_prompt(cards: list[PaperCard]) -> str:
    if not cards:
        return "[]"
    payload = [_card_for_prompt(card) for card in cards]
    return str(payload)


def run_shortlist_critique(
    *,
    problem_statement: str,
    stable_view: list[PaperCard],
    discovery_view: list[PaperCard],
    skill_prompt: str,
) -> ShortlistCritiquePacket:
    """Run the advisory finalize critique."""
    return asyncio.run(
        _critique_shortlist_async(
            problem_statement=problem_statement,
            stable_view=stable_view,
            discovery_view=discovery_view,
            skill_prompt=skill_prompt,
        )
    )
