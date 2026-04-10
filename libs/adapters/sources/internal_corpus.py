"""Internal corpus adapter -- hybrid BM25 + dense retrieval over arxiv_corpus.

This adapter is async and runs over an :class:`AsyncSession` provided by the
caller.  It uses Postgres ``ts_rank_cd`` over the generated ``tsv`` column for
the lexical leg, ``embedding <=> :qvec`` (cosine distance) over pgvector for
the dense leg, and reciprocal rank fusion to merge them.

The lexical and dense legs each request ``top_k`` rows; the union is then
fused, so the result set typically has ``2 * top_k`` candidates capped at
``top_k`` after fusion.

If the embeddings router is unavailable or fails, the adapter degrades to
lexical-only retrieval (logging a warning) so discovery still completes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text

from libs.adapters.sources.base import SourceHit, SourceQuery
from libs.core.logging import get_logger
from libs.discovery.ranking import rrf_fuse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.adapters.embeddings.router import EmbeddingsRouter

log = get_logger(__name__)


_LEXICAL_SQL = text(
    """
    SELECT
        arxiv_id,
        title,
        abstract,
        authors,
        categories,
        created_date,
        doi,
        source_url,
        pdf_url,
        ts_rank_cd(tsv, plainto_tsquery('english', :q)) AS bm25_score
    FROM arxiv_corpus
    WHERE tsv @@ plainto_tsquery('english', :q)
    ORDER BY bm25_score DESC
    LIMIT :k
    """
)


# We bind the vector parameter as TEXT and let pgvector cast it via ``::vector``
# so we don't need a custom SQLAlchemy type for an inline literal.
_DENSE_SQL = text(
    """
    SELECT
        arxiv_id,
        title,
        abstract,
        authors,
        categories,
        created_date,
        doi,
        source_url,
        pdf_url,
        embedding,
        1 - (embedding <=> CAST(:qvec AS vector)) AS dense_score
    FROM arxiv_corpus
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :k
    """
).bindparams(bindparam("qvec", type_=None))


def _row_to_hit(row, *, dense_score: float | None, bm25_score: float | None) -> SourceHit:
    embedding = None
    if "embedding" in row._fields:
        embedding_value = row.embedding
        if embedding_value is not None:
            # pgvector returns a numpy array; coerce to plain list[float].
            embedding = [float(x) for x in embedding_value]

    year = None
    created = row.created_date
    if isinstance(created, str) and len(created) >= 4 and created[:4].isdigit():
        year = int(created[:4])

    return SourceHit(
        source="internal_corpus",
        external_id=str(row.arxiv_id),
        title=row.title or "",
        abstract=row.abstract or "",
        authors=list(row.authors or []),
        categories=list(row.categories or []),
        venue=None,
        year=year,
        published_at=None,
        doi=row.doi or None,
        source_url=row.source_url,
        pdf_url=row.pdf_url,
        embedding=embedding,
        bm25_score=bm25_score,
        dense_score=dense_score,
    )


def _format_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


class InternalCorpusAdapter:
    """Hybrid BM25 + dense source over the local arXiv mirror."""

    name = "internal_corpus"

    def __init__(
        self,
        session: AsyncSession,
        embeddings_router: EmbeddingsRouter | None = None,
        *,
        rrf_k: int = 60,
    ) -> None:
        self._session = session
        self._embeddings = embeddings_router
        self._rrf_k = rrf_k

    async def search(self, query: SourceQuery) -> list[SourceHit]:
        # ---- Lexical leg ------------------------------------------------
        lexical_rows = (
            await self._session.execute(
                _LEXICAL_SQL,
                {"q": query.text, "k": query.top_k},
            )
        ).all()
        lexical_hits: list[SourceHit] = []
        lexical_ids: list[str] = []
        for row in lexical_rows:
            hit = _row_to_hit(row, dense_score=None, bm25_score=float(row.bm25_score))
            lexical_hits.append(hit)
            lexical_ids.append(hit.external_id)

        log.info(
            "internal_corpus.lexical_done",
            query=query.text[:100],
            results=len(lexical_hits),
        )

        # ---- Dense leg --------------------------------------------------
        dense_hits: list[SourceHit] = []
        dense_ids: list[str] = []
        if self._embeddings is not None:
            try:
                qvecs = await self._embeddings.embed([query.text])
                qvec = qvecs[0]
                dense_rows = (
                    await self._session.execute(
                        _DENSE_SQL,
                        {
                            "qvec": _format_pgvector_literal(qvec),
                            "k": query.top_k,
                        },
                    )
                ).all()
                for row in dense_rows:
                    hit = _row_to_hit(
                        row,
                        dense_score=float(row.dense_score),
                        bm25_score=None,
                    )
                    dense_hits.append(hit)
                    dense_ids.append(hit.external_id)
                log.info(
                    "internal_corpus.dense_done",
                    query=query.text[:100],
                    results=len(dense_hits),
                )
            except Exception as exc:
                log.warning(
                    "internal_corpus.dense_failed_falling_back_to_lexical",
                    error=str(exc),
                )

        # ---- Fusion -----------------------------------------------------
        fused_scores = rrf_fuse([lexical_ids, dense_ids], k=self._rrf_k)

        # Build a unified id -> hit map, merging scalar fields and scores.
        merged: dict[str, SourceHit] = {}
        for hit in lexical_hits + dense_hits:
            existing = merged.get(hit.external_id)
            if existing is None:
                merged[hit.external_id] = hit.model_copy()
            else:
                if existing.bm25_score is None and hit.bm25_score is not None:
                    existing.bm25_score = hit.bm25_score
                if existing.dense_score is None and hit.dense_score is not None:
                    existing.dense_score = hit.dense_score
                if existing.embedding is None and hit.embedding is not None:
                    existing.embedding = hit.embedding

        for ext_id, fused_score in fused_scores.items():
            hit = merged.get(ext_id)
            if hit is not None:
                hit.first_stage_score = fused_score

        # Return ranked by fused score, capped at top_k.
        ranked = sorted(
            merged.values(),
            key=lambda h: h.first_stage_score or 0.0,
            reverse=True,
        )
        return ranked[: query.top_k]

    async def close(self) -> None:
        # The session is owned by the caller; nothing to release here.
        return None
