"""Stable and Discovery view construction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.storage.models.papers import PaperCard


def build_stable_view(cards: list[PaperCard], *, top_k: int) -> list[PaperCard]:
    """Top-k by ``final_score`` descending, deterministic tie-break by id."""
    return sorted(
        cards,
        key=lambda c: (-(c.final_score or 0.0), str(c.id)),
    )[:top_k]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _category_overlap(a: list[str] | None, b: list[str] | None) -> float:
    if not a or not b:
        return 0.0
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _similarity(a: PaperCard, b: PaperCard) -> float:
    """Cosine over embeddings if both have one; else Jaccard over categories."""
    if a.embedding and b.embedding:
        return _cosine(list(a.embedding), list(b.embedding))
    return _category_overlap(a.categories, b.categories)


def build_discovery_view(
    cards: list[PaperCard],
    *,
    top_k: int,
    lambda_param: float = 0.7,
) -> list[PaperCard]:
    """Maximal Marginal Relevance diversification.

    ``lambda_param`` of 1.0 reduces to the stable view; 0.0 fully favours
    diversity.  Default is 0.7 which keeps relevance dominant while still
    breaking up clusters of near-duplicates.
    """
    if not cards:
        return []

    # Sort candidates by relevance up front; MMR picks from this pool.
    pool = sorted(cards, key=lambda c: -(c.final_score or 0.0))
    selected: list[PaperCard] = []

    while pool and len(selected) < top_k:
        best_card: PaperCard | None = None
        best_score = -math.inf
        for cand in pool:
            relevance = cand.final_score or 0.0
            penalty = 0.0 if not selected else max(_similarity(cand, sel) for sel in selected)
            mmr_score = lambda_param * relevance - (1 - lambda_param) * penalty
            if mmr_score > best_score:
                best_score = mmr_score
                best_card = cand
        if best_card is None:
            break
        selected.append(best_card)
        pool.remove(best_card)

    return selected
