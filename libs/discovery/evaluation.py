"""Discovery evaluation metrics: Recall@K, Precision@K, MRR.

Computed from a user-supplied set of relevant external_ids and the ranked
``paper_cards`` for a session.  Results are persisted to
``discovery_evaluations``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.storage.models.papers import PaperCard


def recall_at_k(ranked: list[PaperCard], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for c in top if c.external_id in relevant or c.dedupe_key in relevant)
    return hits / len(relevant)


def precision_at_k(ranked: list[PaperCard], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    hits = sum(1 for c in top if c.external_id in relevant or c.dedupe_key in relevant)
    return hits / len(top)


def mrr(ranked: list[PaperCard], relevant: set[str]) -> float:
    for idx, card in enumerate(ranked, start=1):
        if card.external_id in relevant or card.dedupe_key in relevant:
            return 1.0 / idx
    return 0.0
