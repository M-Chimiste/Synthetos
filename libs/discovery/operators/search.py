"""discovery_search operator -- runs source adapters, dedupes, persists cards.

Source selection is driven by ``ProblemProfile.source_scope`` (a JSON dict).
Phase 1 supports two boolean flags: ``internal_corpus`` and ``arxiv_live``.
Both default to True if the dict is missing or empty.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.adapters.embeddings.router import EmbeddingsRouter
from libs.adapters.sources.arxiv_live import ArxivLiveAdapter
from libs.adapters.sources.base import SourceHit, SourceQuery
from libs.adapters.sources.dedupe import dedupe_hits, dedupe_key
from libs.adapters.sources.internal_corpus import InternalCorpusAdapter
from libs.core.clock import utcnow
from libs.core.event_types import DiscoveryEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.discovery.operators._common import (
    DiscoveryStateError,
    append_step_log,
    enqueue_next,
    load_profile,
    load_session,
    merge_stats,
    session_id_from_payload,
)
from libs.discovery.ranking import normalize_scores, rrf_fuse
from libs.patterns.embedding import embed_text
from libs.patterns.injection import InjectionPolicy, inject_patterns
from libs.storage.base import get_async_session_factory, get_sync_session_factory
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCycle

log = get_logger(__name__)


_DEFAULT_SCOPE = {"internal_corpus": True, "arxiv_live": True}
_SOURCE_RRF_K = 60


def _scope_flags(profile_scope: dict[str, Any] | None) -> dict[str, bool]:
    scope = dict(_DEFAULT_SCOPE)
    if profile_scope:
        for key in scope:
            if key in profile_scope:
                scope[key] = bool(profile_scope[key])
    return scope


async def _search_internal(
    db: AsyncSession,
    query: SourceQuery,
) -> list[SourceHit]:
    embeddings = EmbeddingsRouter()
    try:
        adapter = InternalCorpusAdapter(db, embeddings_router=embeddings)
        return await adapter.search(query)
    finally:
        await embeddings.close()


async def _search_external(query: SourceQuery) -> list[SourceHit]:
    adapter = ArxivLiveAdapter()
    try:
        return await adapter.search(query)
    finally:
        await adapter.close()


async def _run_search(
    *,
    profile_text: str,
    categories: list[str],
    scope: dict[str, bool],
    budget: dict[str, Any],
) -> tuple[list[SourceHit], dict[str, int]]:
    """Coordinate the source fan-out and dedupe.

    Returns ``(deduped_hits, per_source_counts)``.
    """
    internal_top_k = int(budget.get("max_internal_results", 200))
    external_top_k = int(budget.get("max_external_results", 50))

    counts: dict[str, int] = {}
    internal_hits: list[SourceHit] = []
    external_hits: list[SourceHit] = []

    if scope.get("internal_corpus"):
        factory = get_async_session_factory()
        async with factory() as db:
            internal_hits = await _search_internal(
                db,
                SourceQuery(text=profile_text, top_k=internal_top_k, categories=categories),
            )
        counts["internal_corpus"] = len(internal_hits)

    if scope.get("arxiv_live") and external_top_k > 0:
        try:
            external_hits = await _search_external(
                SourceQuery(text=profile_text, top_k=external_top_k, categories=categories),
            )
        except Exception as exc:
            log.warning("discovery_search.arxiv_live_failed", error=str(exc))
            external_hits = []
        counts["arxiv_live"] = len(external_hits)

    source_rankings = [
        _ranked_dedupe_keys(internal_hits),
        _ranked_dedupe_keys(external_hits),
    ]
    fused_scores = normalize_scores(
        rrf_fuse([ranking for ranking in source_rankings if ranking], k=_SOURCE_RRF_K)
    )

    # Internal hits go first so dedupe prefers the embedded copy.
    combined = internal_hits + external_hits
    deduped, dropped = dedupe_hits(combined)
    for hit in deduped:
        hit.first_stage_score = fused_scores.get(dedupe_key(hit), 0.0)

    counts["dropped_duplicates"] = dropped
    counts["deduped"] = len(deduped)
    counts["sources_fused"] = sum(1 for ranking in source_rankings if ranking)
    return deduped, counts


def _ranked_dedupe_keys(hits: list[SourceHit]) -> list[str]:
    ranked: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        key = dedupe_key(hit)
        if key in seen:
            continue
        seen.add(key)
        ranked.append(key)
    return ranked


def _search_hints(profile_scope: dict[str, Any] | None) -> tuple[str | None, list[str], list[str]]:
    hints = dict((profile_scope or {}).get("search_hints") or {})
    derived_query = hints.get("derived_query")
    synonyms = hints.get("synonyms") or []
    categories = hints.get("categories") or []
    return (
        str(derived_query).strip() if derived_query else None,
        [str(item).strip() for item in synonyms if str(item).strip()],
        [str(item).strip() for item in categories if str(item).strip()],
    )


def _apply_pattern_hints(
    *,
    query_text: str,
    categories: list[str],
    pattern_matches: list,
) -> tuple[str, list[str], list[str]]:
    """Turn retrieval-heuristic patterns into deterministic search hints."""
    extra_terms: list[str] = []
    extra_categories: list[str] = []
    applied_ids: list[str] = []
    seen_terms: set[str] = set()
    seen_categories: set[str] = set(categories)

    for match in pattern_matches:
        applied_ids.append(str(match.pattern.id))
        body = match.pattern.structured_body or {}
        heuristic_kind = body.get("heuristic_kind")
        if isinstance(heuristic_kind, str) and heuristic_kind.strip():
            term = heuristic_kind.replace("_", " ").strip()
            if term and term not in seen_terms:
                seen_terms.add(term)
                extra_terms.append(term)

        params = body.get("parameters") or {}
        next_action = params.get("next_action")
        if isinstance(next_action, str) and next_action.strip():
            term = next_action.replace("_", " ").strip()
            if term and term not in seen_terms:
                seen_terms.add(term)
                extra_terms.append(term)

        raw_categories = body.get("categories") or []
        if isinstance(raw_categories, list):
            for category in raw_categories:
                value = str(category).strip()
                if value and value not in seen_categories:
                    seen_categories.add(value)
                    extra_categories.append(value)

    if extra_terms:
        query_text = " ".join([query_text, *extra_terms]).strip()
    return query_text, categories + extra_categories, applied_ids


def _hit_to_card(
    hit: SourceHit,
    *,
    session_id,
    charter_id,
) -> PaperCard:
    return PaperCard(
        id=uuid7(),
        session_id=session_id,
        charter_id=charter_id,
        source=hit.source,
        external_id=hit.external_id,
        dedupe_key=dedupe_key(hit),
        title=hit.title or "",
        abstract=hit.abstract or "",
        authors=hit.authors,
        categories=hit.categories,
        venue=hit.venue,
        year=hit.year,
        published_at=hit.published_at,
        doi=hit.doi,
        source_url=hit.source_url,
        pdf_url=hit.pdf_url,
        embedding=hit.embedding,
        bm25_score=hit.bm25_score,
        dense_score=hit.dense_score,
        first_stage_score=hit.first_stage_score,
        rerank_score=None,
        final_score=hit.first_stage_score,
        triage_status="discovered",
        view_membership=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )


def discovery_search_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        session_id = session_id_from_payload(op_input)
    except DiscoveryStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as session:
        try:
            discovery = load_session(session, session_id)
            profile = load_profile(session, discovery.profile_id)
        except DiscoveryStateError as exc:
            return OperatorResult(success=False, error=str(exc))

        scope = _scope_flags(profile.source_scope)
        budget = profile.budget or {}
        derived_query, synonyms, categories = _search_hints(profile.source_scope)
        query_text = derived_query or profile.query_text
        if synonyms:
            query_text = " ".join([query_text, *synonyms[:8]])

        cycle = session.get(ResearchCycle, discovery.cycle_id)
        pattern_policy = InjectionPolicy.from_cycle_config(cycle.config if cycle else None)
        query_embedding = embed_text(query_text)
        pattern_matches = inject_patterns(
            session,
            charter_id=discovery.charter_id,
            current_cycle_id=discovery.cycle_id,
            types=["retrieval_heuristic"],
            policy=pattern_policy,
            problem_profile_embedding=query_embedding,
            operator_name="discovery_search",
        )
        query_text, categories, pattern_ids = _apply_pattern_hints(
            query_text=query_text,
            categories=categories,
            pattern_matches=pattern_matches,
        )

        try:
            hits, counts = asyncio.run(
                _run_search(
                    profile_text=query_text,
                    categories=categories,
                    scope=scope,
                    budget=budget,
                )
            )
        except Exception as exc:
            log.exception("discovery_search.failed", error=str(exc))
            return OperatorResult(success=False, error=f"discovery_search failed: {exc}")

        for hit in hits:
            card = _hit_to_card(
                hit,
                session_id=discovery.id,
                charter_id=discovery.charter_id,
            )
            session.add(card)

        discovery.status = "search_complete"
        merge_stats(discovery, {"search": counts})
        append_step_log(
            discovery,
            step="search",
            status="ok",
            detail={
                "scope": scope,
                "query_text": query_text,
                "categories": categories,
                "pattern_ids": pattern_ids,
                "counts": counts,
            },
        )

        enqueue_next(
            session,
            cycle_id=discovery.cycle_id,
            next_job_type="discovery_rerank",
            session_id=discovery.id,
        )
        session.commit()

    result = OperatorResult(
        success=True,
        summary=(
            f"Search complete; persisted {counts.get('deduped', 0)} cards "
            f"({counts.get('dropped_duplicates', 0)} duplicates dropped)"
        ),
    )
    result.add_event(
        DiscoveryEvents.papers_discovered.value,
        {
            "session_id": str(session_id),
            "counts": counts,
            "scope": scope,
            "query_text": query_text,
            "categories": categories,
        },
    )
    result.add_event(
        DiscoveryEvents.sources_deduped.value,
        {
            "session_id": str(session_id),
            "deduped": counts.get("deduped", 0),
            "dropped": counts.get("dropped_duplicates", 0),
        },
    )
    return result
