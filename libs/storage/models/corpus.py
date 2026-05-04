"""arXiv corpus SQLAlchemy models.

The corpus table holds the system-wide pre-embedded arXiv metadata mirror.
It is populated once by ``synthetos corpus import-arxiv`` from the JSONL
dump under ``artifacts/`` and incrementally updated by the live arXiv adapter.

Each row carries:
  * scalar metadata (id, title, abstract, authors, categories, dates, urls)
  * a precomputed ``search_text`` blob
  * a content hash for deduplication
  * a 768-dim ``gte-modernbert-base`` embedding stored in pgvector
  * a generated ``tsv`` ``tsvector`` column for BM25-style lexical retrieval

Indexes:
  * GIN on the generated ``tsv`` column for full-text search
  * HNSW on ``embedding`` for cosine similarity search

Both indexes are created by the Phase 1 Alembic migration -- they are *not*
managed via ``__table_args__`` because pgvector's HNSW index needs custom
``USING`` syntax.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class ArxivCorpusRecord(Base):
    """One row in the local arXiv mirror.

    Primary key is the arXiv id (e.g. ``"0704.0001"``) -- not a UUID, since
    the arXiv id is naturally unique and small.
    """

    __tablename__ = "arxiv_corpus"

    arxiv_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 768-dim gte-modernbert embedding
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    embedding_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_updated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Generated tsvector for full-text search; built from title + abstract.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    imported_at: Mapped[datetime] = mapped_column(default=utcnow)


class CorpusImportRun(Base):
    """Tracks resumable corpus import progress for one source dump."""

    __tablename__ = "corpus_import_runs"
    __table_args__ = (
        Index("ix_corpus_import_runs_source_started", "source_path", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source_path: Mapped[str] = mapped_column(String(1024))
    mode: Mapped[str] = mapped_column(String(32), default="copy")
    status: Mapped[str] = mapped_column(String(32), default="running")
    last_line: Mapped[int] = mapped_column(Integer, default=0)
    last_arxiv_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
