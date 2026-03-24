"""Pattern retrieval service: hybrid search over canonical patterns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from libs.adapters.embeddings.base import EmbeddingAdapter
from libs.storage.models import CanonicalPatternModel


@dataclass
class PatternSearchHit:
    pattern: CanonicalPatternModel
    hybrid_score: float
    vector_score: float | None
    lexical_score: float | None


class PatternRetrievalService:
    """Hybrid lexical+vector search over canonical_patterns, mirroring ArxivWarehouseService."""

    def __init__(self, embedder: EmbeddingAdapter) -> None:
        self.embedder = embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        session: Session,
        *,
        query_text: str,
        pattern_types: list[str] | None = None,
        polarity: str | None = None,
        category_prefix: str | None = None,
        min_confidence: float = 0.3,
        limit: int = 10,
        candidate_pool: int = 50,
    ) -> list[PatternSearchHit]:
        """Hybrid search (0.5*lexical + 0.5*vector) over active canonical patterns."""
        query_text = query_text.strip()
        if not query_text:
            return []

        vector = self.embedder.embed_query(query_text)
        filters = self._build_filters(pattern_types, polarity, category_prefix, min_confidence)

        lexical_rows = self._run_lexical_query(
            session, query_text=query_text, filters=filters, limit=max(limit, candidate_pool),
        )
        vector_rows = self._run_vector_query(
            session, vector=vector, filters=filters, limit=max(limit, candidate_pool),
        )

        return self._merge_and_rank(session, lexical_rows, vector_rows, limit)

    def get_failure_patterns(
        self,
        session: Session,
        *,
        failure_class: str | None = None,
        category_prefix: str | None = None,
        min_confidence: float = 0.3,
    ) -> list[CanonicalPatternModel]:
        """Direct lookup for failure patterns, optionally by failure_class."""
        stmt = (
            select(CanonicalPatternModel)
            .where(CanonicalPatternModel.pattern_type == "failure_pattern")
            .where(CanonicalPatternModel.status.in_(["active", "confirmed"]))
            .where(CanonicalPatternModel.confidence_score >= min_confidence)
            .order_by(CanonicalPatternModel.confidence_score.desc())
        )
        if category_prefix:
            stmt = stmt.where(CanonicalPatternModel.category.startswith(category_prefix))

        patterns = list(session.scalars(stmt).all())

        if failure_class:
            patterns = [
                p for p in patterns
                if failure_class in (p.trigger_conditions or [])
            ]

        return patterns

    def get_method_patterns(
        self,
        session: Session,
        *,
        query_text: str,
        category_prefix: str | None = None,
        limit: int = 5,
        min_confidence: float = 0.3,
    ) -> list[PatternSearchHit]:
        """Semantic search for positive method patterns."""
        return self.search(
            session,
            query_text=query_text,
            pattern_types=["method_pattern"],
            polarity="positive",
            category_prefix=category_prefix,
            min_confidence=min_confidence,
            limit=limit,
        )

    def get_signal_patterns(
        self,
        session: Session,
        *,
        query_text: str,
        limit: int = 5,
    ) -> list[PatternSearchHit]:
        """Semantic search for signal patterns."""
        return self.search(
            session,
            query_text=query_text,
            pattern_types=["signal_pattern"],
            limit=limit,
        )

    def list_categories(self, session: Session) -> list[str]:
        """Return all distinct category values for ontology browsing."""
        stmt = (
            select(CanonicalPatternModel.category)
            .where(CanonicalPatternModel.category != "")
            .distinct()
            .order_by(CanonicalPatternModel.category)
        )
        return list(session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filters(
        pattern_types: list[str] | None,
        polarity: str | None,
        category_prefix: str | None,
        min_confidence: float,
    ) -> dict[str, Any]:
        return {
            "pattern_types_csv": ",".join(pattern_types) if pattern_types else "",
            "polarity": polarity or "",
            "category_prefix": (category_prefix or "") + "%" if category_prefix else "",
            "min_confidence": min_confidence,
        }

    @staticmethod
    def _run_lexical_query(
        session: Session,
        *,
        query_text: str,
        filters: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query_text:
            return []
        sql = text("""
            SELECT id,
                   ts_rank_cd(
                       to_tsvector('english', search_text),
                       websearch_to_tsquery('english', :query_text)
                   ) AS lexical_score
            FROM canonical_patterns
            WHERE to_tsvector('english', search_text)
                  @@ websearch_to_tsquery('english', :query_text)
              AND status IN ('active', 'confirmed')
              AND confidence_score >= :min_confidence
              AND (:pattern_types_csv = ''
                   OR pattern_type = ANY(string_to_array(:pattern_types_csv, ',')))
              AND (:polarity = '' OR polarity = :polarity)
              AND (:category_prefix = '' OR category LIKE :category_prefix)
            ORDER BY lexical_score DESC
            LIMIT :limit
        """)
        result = session.execute(sql, {
            "query_text": query_text,
            **filters,
            "limit": limit,
        })
        return [dict(row._mapping) for row in result]

    def _run_vector_query(
        self,
        session: Session,
        *,
        vector: list[float],
        filters: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not vector:
            return []
        sql = text("""
            SELECT id,
                   GREATEST(0.0, 1.0 - (embedding <=> CAST(:embedding AS vector))) AS vector_score
            FROM canonical_patterns
            WHERE embedding IS NOT NULL
              AND status IN ('active', 'confirmed')
              AND confidence_score >= :min_confidence
              AND (:pattern_types_csv = ''
                   OR pattern_type = ANY(string_to_array(:pattern_types_csv, ',')))
              AND (:polarity = '' OR polarity = :polarity)
              AND (:category_prefix = '' OR category LIKE :category_prefix)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        result = session.execute(sql, {
            "embedding": self._vector_literal(vector),
            **filters,
            "limit": limit,
        })
        return [dict(row._mapping) for row in result]

    @staticmethod
    def _merge_and_rank(
        session: Session,
        lexical_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        limit: int,
    ) -> list[PatternSearchHit]:
        hit_ids = {row["id"] for row in lexical_rows} | {row["id"] for row in vector_rows}
        if not hit_ids:
            return []

        lexical_scores = {row["id"]: float(row["lexical_score"]) for row in lexical_rows}
        vector_scores = {row["id"]: float(row["vector_score"]) for row in vector_rows}
        max_lexical = max(lexical_scores.values(), default=0.0) or 1.0

        patterns = session.scalars(
            select(CanonicalPatternModel).where(CanonicalPatternModel.id.in_(hit_ids))
        ).all()
        pattern_map = {p.id: p for p in patterns}

        hits: list[PatternSearchHit] = []
        for pid in hit_ids:
            pattern = pattern_map.get(pid)
            if pattern is None:
                continue
            lex = lexical_scores.get(pid)
            vec = vector_scores.get(pid)
            lex_norm = (lex / max_lexical) if lex is not None else 0.0
            vec_norm = vec if vec is not None else 0.0
            hybrid = 0.5 * lex_norm + 0.5 * vec_norm
            hits.append(PatternSearchHit(
                pattern=pattern,
                hybrid_score=hybrid,
                vector_score=vec,
                lexical_score=lex,
            ))

        hits.sort(key=lambda h: h.hybrid_score, reverse=True)
        return hits[:limit]

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{float(v):.12g}" for v in vector) + "]"
