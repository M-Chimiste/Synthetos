"""Ranking utilities for the Phase 1 discovery pipeline."""

from __future__ import annotations

from collections.abc import Iterable


def rrf_fuse(rankings: Iterable[Iterable[str]], *, k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion.

    Given several ranked lists of document ids, returns a dict mapping
    each id to its fused score:

        score(d) = sum_i 1 / (k + rank_i(d))

    Higher score is better.  Documents that appear in more lists at higher
    ranks accumulate more score.

    The classic value of ``k=60`` from the original RRF paper is the default.
    """
    fused: dict[str, float] = {}
    for ranked in rankings:
        for rank, doc_id in enumerate(ranked):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


def normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    """Min-max normalize a score map into ``[0, 1]``.

    Returns the input unchanged when fewer than two distinct values are
    present.
    """
    if not scores:
        return {}
    values = list(scores.values())
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}
