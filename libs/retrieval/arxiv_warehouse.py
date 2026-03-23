from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from libs.adapters.arxiv.adapter import ArxivAdapterConfig, ArxivMetadataAdapter
from libs.adapters.embeddings import (
    EmbeddingAdapter,
    SentenceTransformerEmbeddingAdapter,
)
from libs.adapters.literature import RawPaperRecord, SourceQuery
from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.storage.models import ArxivPaperModel, ArxivSyncRunModel

log = structlog.get_logger(__name__)

_KAGGLE_DATASET = "cornell-university/arxiv"


@dataclass
class ArxivSearchHit:
    paper: ArxivPaperModel
    hybrid_score: float
    vector_score: float | None
    lexical_score: float | None


@dataclass
class _CanonicalPaper:
    arxiv_id: str
    title: str
    abstract: str | None
    authors: list[str]
    categories: list[str]
    created_date: datetime | None
    updated_date: datetime | None
    doi: str | None
    source_url: str
    pdf_url: str | None
    raw_metadata: dict[str, Any]
    search_text: str
    content_hash: str


class ArxivWarehouseService:
    def __init__(self, config: AppConfig, embedder: EmbeddingAdapter | None = None):
        self.config = config
        self.embedder = embedder or SentenceTransformerEmbeddingAdapter(config.embedding)

    def ensure_fresh(
        self,
        session: Session,
        *,
        target_until: datetime | None = None,
    ) -> list[ArxivSyncRunModel]:
        self._require_postgres()
        completed = self.latest_completed_sync(session)
        sync_runs: list[ArxivSyncRunModel] = []
        if completed is None:
            sync_runs.append(self.sync_full(session))
            completed = sync_runs[-1]

        stale_after = completed.updated_at + timedelta(hours=self.config.arxiv_sync_freshness_hours)
        target = target_until or datetime.now(UTC)
        covered_until = (
            completed.cursor_updated_until
            or completed.effective_until
            or completed.updated_at
        )
        if stale_after < datetime.now(UTC) or covered_until is None or covered_until < target:
            sync_runs.append(self.sync_incremental(session, requested_until=target))
        return sync_runs

    def sync_full(self, session: Session) -> ArxivSyncRunModel:
        self._require_postgres()
        snapshot_path = self.ensure_snapshot_path()
        run = ArxivSyncRunModel(
            public_id=generate_public_id("arxivsync"),
            mode="full",
            source="kaggle",
            status="running",
        )
        session.add(run)
        session.commit()
        try:
            stats = self._upsert_records(
                session,
                (
                    self._canonicalize_snapshot_row(row)
                    for row in self.iter_snapshot_rows(snapshot_path)
                ),
            )
            self._finalize_run(run, stats)
            session.commit()
            return run
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            session.commit()
            raise

    def sync_incremental(
        self,
        session: Session,
        *,
        requested_until: datetime | None = None,
    ) -> ArxivSyncRunModel:
        self._require_postgres()
        latest = self.latest_completed_sync(session)
        requested_from = latest.cursor_updated_until if latest else None
        requested_until = requested_until or datetime.now(UTC)
        run = ArxivSyncRunModel(
            public_id=generate_public_id("arxivsync"),
            mode="incremental",
            source="oai_pmh",
            status="running",
            requested_from=requested_from,
            requested_until=requested_until,
        )
        session.add(run)
        session.commit()
        try:
            query = SourceQuery(
                categories=[],
                date_from=self._format_oai_date(requested_from),
                date_until=self._format_oai_date(requested_until),
                max_results=0,
            )
            adapter = ArxivMetadataAdapter(ArxivAdapterConfig(max_results=None))
            stats = self._upsert_records(
                session,
                (self._canonicalize_raw_record(record) for record in adapter.search(query)),
            )
            self._finalize_run(
                run, stats,
                requested_from=requested_from,
                requested_until=requested_until,
            )
            session.commit()
            return run
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            session.commit()
            raise

    def search(
        self,
        session: Session,
        *,
        query_text: str,
        limit: int = 20,
        categories: list[str] | None = None,
        date_from: datetime | None = None,
        date_until: datetime | None = None,
        candidate_pool: int = 100,
    ) -> list[ArxivSearchHit]:
        self._require_postgres()
        query_text = query_text.strip()
        categories = [item for item in (categories or []) if item]
        vector = self.embedder.embed_query(query_text)
        lexical_rows = self._run_lexical_query(
            session,
            query_text=query_text,
            categories=categories,
            date_from=date_from,
            date_until=date_until,
            limit=max(limit, candidate_pool),
        )
        vector_rows = self._run_vector_query(
            session,
            vector=vector,
            categories=categories,
            date_from=date_from,
            date_until=date_until,
            limit=max(limit, candidate_pool),
        )
        hit_ids = {row["id"] for row in lexical_rows} | {row["id"] for row in vector_rows}
        if not hit_ids:
            return []

        lexical_scores = {row["id"]: float(row["lexical_score"]) for row in lexical_rows}
        vector_scores = {row["id"]: float(row["vector_score"]) for row in vector_rows}
        max_lexical = max(lexical_scores.values(), default=0.0) or 1.0
        papers = session.scalars(
            select(ArxivPaperModel).where(ArxivPaperModel.id.in_(hit_ids))
        ).all()
        paper_map = {paper.id: paper for paper in papers}

        hits: list[ArxivSearchHit] = []
        for paper_id in hit_ids:
            paper = paper_map.get(paper_id)
            if paper is None:
                continue
            lexical = lexical_scores.get(paper_id)
            vector_score = vector_scores.get(paper_id)
            lexical_norm = (lexical / max_lexical) if lexical is not None else 0.0
            vector_norm = vector_score if vector_score is not None else 0.0
            hybrid = (0.5 * lexical_norm) + (0.5 * vector_norm)
            hits.append(
                ArxivSearchHit(
                    paper=paper,
                    hybrid_score=hybrid,
                    vector_score=vector_score,
                    lexical_score=lexical,
                )
            )
        hits.sort(key=lambda item: item.hybrid_score, reverse=True)
        return hits[:limit]

    def latest_completed_sync(self, session: Session) -> ArxivSyncRunModel | None:
        return session.scalar(
            select(ArxivSyncRunModel)
            .where(ArxivSyncRunModel.status == "completed")
            .order_by(ArxivSyncRunModel.updated_at.desc())
            .limit(1)
        )

    def recent_sync_runs(self, session: Session, limit: int = 5) -> list[ArxivSyncRunModel]:
        return list(
            session.scalars(
                select(ArxivSyncRunModel)
                .order_by(ArxivSyncRunModel.created_at.desc())
                .limit(limit)
            ).all()
        )

    def paper_to_raw_record(self, hit: ArxivSearchHit) -> RawPaperRecord:
        paper = hit.paper
        metadata_extra = dict(paper.raw_metadata or {})
        metadata_extra.update({
            "doi": paper.doi,
            "updated": paper.updated_date.date().isoformat() if paper.updated_date else None,
            "warehouse_public_id": paper.public_id,
            "hybrid_score": hit.hybrid_score,
            "vector_score": hit.vector_score,
            "lexical_score": hit.lexical_score,
        })
        metadata_extra = {key: value for key, value in metadata_extra.items() if value is not None}
        return RawPaperRecord(
            external_id=paper.arxiv_id,
            title=paper.title,
            abstract=paper.abstract,
            authors=list(paper.authors or []),
            categories=list(paper.categories or []),
            publication_date=paper.created_date.date().isoformat() if paper.created_date else None,
            source_url=paper.source_url,
            pdf_url=paper.pdf_url,
            source_type="arxiv",
            metadata_extra=metadata_extra,
        )

    def ensure_snapshot_path(self) -> Path:
        snapshot_path = self.config.arxiv_snapshot_path
        if snapshot_path.exists():
            return snapshot_path

        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if "KAGGLE_CONFIG_DIR" not in env:
            kaggle_dir = Path.home() / ".kaggle"
            if kaggle_dir.exists():
                env["KAGGLE_CONFIG_DIR"] = str(kaggle_dir)

        cmd = [
            "kaggle",
            "datasets",
            "download",
            _KAGGLE_DATASET,
            "--path",
            str(snapshot_path.parent),
            "--unzip",
        ]
        try:
            subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Kaggle CLI is required to download the arXiv snapshot. "
                "Install project dependencies or set LAB_ARXIV_KAGGLE_DATASET."
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "unknown Kaggle error"
            raise RuntimeError(f"Failed to download Kaggle arXiv snapshot: {stderr}") from exc

        if snapshot_path.exists():
            return snapshot_path

        candidates = list(snapshot_path.parent.glob("arxiv-metadata-oai-snapshot*.json"))
        if not candidates:
            raise RuntimeError(
                "Kaggle download completed but the arXiv snapshot file was not found."
            )
        candidates.sort()
        return candidates[0]

    def iter_snapshot_rows(self, path: Path) -> Iterator[dict[str, Any]]:
        first = self._first_non_whitespace(path)
        if first == "[":
            yield from self._iter_json_array(path)
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    record = json.loads(payload)
                except JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record

    def _run_lexical_query(
        self,
        session: Session,
        *,
        query_text: str,
        categories: list[str],
        date_from: datetime | None,
        date_until: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query_text:
            return []
        sql = text(
            """
            SELECT id,
                   ts_rank_cd(
                       to_tsvector('english', search_text),
                       websearch_to_tsquery('english', :query_text)
                   ) AS lexical_score
            FROM arxiv_papers
            WHERE to_tsvector('english', search_text)
                  @@ websearch_to_tsquery('english', :query_text)
              AND (:categories_csv = '' OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(categories::jsonb) AS category
                    WHERE category = ANY(string_to_array(:categories_csv, ','))
                  ))
              AND (:date_from IS NULL OR created_date >= :date_from)
              AND (:date_until IS NULL OR created_date <= :date_until)
            ORDER BY lexical_score DESC
            LIMIT :limit
            """
        )
        result = session.execute(
            sql,
            {
                "query_text": query_text,
                "categories_csv": ",".join(categories),
                "date_from": date_from,
                "date_until": date_until,
                "limit": limit,
            },
        )
        return [dict(row._mapping) for row in result]

    def _run_vector_query(
        self,
        session: Session,
        *,
        vector: list[float],
        categories: list[str],
        date_from: datetime | None,
        date_until: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not vector:
            return []
        sql = text(
            """
            SELECT id,
                   GREATEST(0.0, 1.0 - (embedding <=> CAST(:embedding AS vector))) AS vector_score
            FROM arxiv_papers
            WHERE embedding IS NOT NULL
              AND (:categories_csv = '' OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(categories::jsonb) AS category
                    WHERE category = ANY(string_to_array(:categories_csv, ','))
                  ))
              AND (:date_from IS NULL OR created_date >= :date_from)
              AND (:date_until IS NULL OR created_date <= :date_until)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        )
        result = session.execute(
            sql,
            {
                "embedding": self._vector_literal(vector),
                "categories_csv": ",".join(categories),
                "date_from": date_from,
                "date_until": date_until,
                "limit": limit,
            },
        )
        return [dict(row._mapping) for row in result]

    def _upsert_records(
        self,
        session: Session,
        papers: Iterator[_CanonicalPaper],
    ) -> dict[str, Any]:
        inserted = 0
        updated = 0
        reembedded = 0
        skipped = 0
        first_effective: datetime | None = None
        last_effective: datetime | None = None

        batch: list[_CanonicalPaper] = []
        for paper in papers:
            batch.append(paper)
            if len(batch) >= 128:
                stats = self._upsert_batch(session, batch)
                session.commit()
                session.expire_all()
                inserted += stats["inserted"]
                updated += stats["updated"]
                reembedded += stats["reembedded"]
                skipped += stats["skipped"]
                first_effective, last_effective = self._merge_effective_range(
                    first_effective,
                    last_effective,
                    stats["effective_from"],
                    stats["effective_until"],
                )
                batch = []
        if batch:
            stats = self._upsert_batch(session, batch)
            session.commit()
            session.expire_all()
            inserted += stats["inserted"]
            updated += stats["updated"]
            reembedded += stats["reembedded"]
            skipped += stats["skipped"]
            first_effective, last_effective = self._merge_effective_range(
                first_effective,
                last_effective,
                stats["effective_from"],
                stats["effective_until"],
            )
        return {
            "inserted": inserted,
            "updated": updated,
            "reembedded": reembedded,
            "skipped": skipped,
            "effective_from": first_effective,
            "effective_until": last_effective,
        }

    def _upsert_batch(self, session: Session, batch: list[_CanonicalPaper]) -> dict[str, Any]:
        ids = [paper.arxiv_id for paper in batch]
        existing_rows = session.scalars(
            select(ArxivPaperModel).where(ArxivPaperModel.arxiv_id.in_(ids))
        ).all()
        existing = {row.arxiv_id: row for row in existing_rows}
        pending_rows: list[ArxivPaperModel] = []
        pending_texts: list[str] = []
        inserted = 0
        updated = 0
        skipped = 0
        effective_dates = [paper.updated_date or paper.created_date for paper in batch]
        effective_dates = [date for date in effective_dates if date is not None]

        for paper in batch:
            row = existing.get(paper.arxiv_id)
            changed = row is None
            previous_hash = row.content_hash if row is not None else None
            if row is None:
                row = ArxivPaperModel(
                    public_id=generate_public_id("arxiv"),
                    arxiv_id=paper.arxiv_id,
                    title=paper.title,
                    abstract=paper.abstract,
                    authors=paper.authors,
                    categories=paper.categories,
                    created_date=paper.created_date,
                    updated_date=paper.updated_date,
                    doi=paper.doi,
                    source_url=paper.source_url,
                    pdf_url=paper.pdf_url,
                    search_text=paper.search_text,
                    content_hash=paper.content_hash,
                    raw_metadata=paper.raw_metadata,
                )
                session.add(row)
                inserted += 1
            else:
                fields = {
                    "title": paper.title,
                    "abstract": paper.abstract,
                    "authors": paper.authors,
                    "categories": paper.categories,
                    "created_date": paper.created_date,
                    "updated_date": paper.updated_date,
                    "doi": paper.doi,
                    "source_url": paper.source_url,
                    "pdf_url": paper.pdf_url,
                    "search_text": paper.search_text,
                    "content_hash": paper.content_hash,
                    "raw_metadata": paper.raw_metadata,
                }
                for key, value in fields.items():
                    if not self._same_value(getattr(row, key), value):
                        setattr(row, key, value)
                        changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1

            needs_embedding = (
                row.embedding is None
                or previous_hash != paper.content_hash
                or row.embedding_model_id != self.config.embedding.model_id
            )
            if needs_embedding:
                pending_rows.append(row)
                pending_texts.append(paper.search_text)

        if pending_texts:
            vectors = self.embedder.embed_documents(pending_texts)
            now = datetime.now(UTC)
            for row, vector in zip(pending_rows, vectors, strict=True):
                row.embedding = vector
                row.embedding_model_id = self.config.embedding.model_id
                row.embedding_updated_at = now
            session.flush()
        else:
            session.flush()

        return {
            "inserted": inserted,
            "updated": updated,
            "reembedded": len(pending_rows),
            "skipped": skipped,
            "effective_from": min(effective_dates) if effective_dates else None,
            "effective_until": max(effective_dates) if effective_dates else None,
        }

    def _canonicalize_snapshot_row(self, row: dict[str, Any]) -> _CanonicalPaper:
        arxiv_id = str(row.get("id") or row.get("arxiv_id") or "").strip()
        if not arxiv_id:
            raise ValueError("Snapshot row is missing arxiv id")
        title = str(row.get("title") or "").strip()
        abstract = str(row.get("abstract") or "").strip() or None
        authors = self._parse_snapshot_authors(row)
        categories = sorted({item for item in str(row.get("categories") or "").split() if item})
        created = self._parse_snapshot_created(row)
        updated = self._parse_datetime(row.get("update_date")) or created
        doi = str(row.get("doi") or "").strip() or None
        source_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        search_text = self._build_search_text(title, abstract)
        return _CanonicalPaper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            authors=authors,
            categories=categories,
            created_date=created,
            updated_date=updated,
            doi=doi,
            source_url=source_url,
            pdf_url=pdf_url,
            raw_metadata=row,
            search_text=search_text,
            content_hash=self._content_hash(title, abstract),
        )

    def _canonicalize_raw_record(self, record: RawPaperRecord) -> _CanonicalPaper:
        created = self._parse_datetime(record.publication_date)
        updated = self._parse_datetime(record.metadata_extra.get("updated")) or created
        search_text = self._build_search_text(record.title, record.abstract)
        return _CanonicalPaper(
            arxiv_id=record.external_id,
            title=record.title,
            abstract=record.abstract,
            authors=list(record.authors or []),
            categories=list(record.categories or []),
            created_date=created,
            updated_date=updated,
            doi=str(record.metadata_extra.get("doi") or "").strip() or None,
            source_url=record.source_url or f"https://arxiv.org/abs/{record.external_id}",
            pdf_url=record.pdf_url,
            raw_metadata=dict(record.metadata_extra or {}),
            search_text=search_text,
            content_hash=self._content_hash(record.title, record.abstract),
        )

    def _finalize_run(
        self,
        run: ArxivSyncRunModel,
        stats: dict[str, Any],
        *,
        requested_from: datetime | None = None,
        requested_until: datetime | None = None,
    ) -> None:
        run.status = "completed"
        run.requested_from = requested_from or run.requested_from
        run.requested_until = requested_until or run.requested_until
        run.effective_from = stats["effective_from"]
        run.effective_until = stats["effective_until"]
        run.cursor_updated_until = stats["effective_until"] or requested_until
        run.inserted_count = stats["inserted"]
        run.updated_count = stats["updated"]
        run.reembedded_count = stats["reembedded"]
        run.skipped_count = stats["skipped"]

    def _merge_effective_range(
        self,
        current_from: datetime | None,
        current_until: datetime | None,
        new_from: datetime | None,
        new_until: datetime | None,
    ) -> tuple[datetime | None, datetime | None]:
        starts = [item for item in [current_from, new_from] if item is not None]
        ends = [item for item in [current_until, new_until] if item is not None]
        return (min(starts) if starts else None, max(ends) if ends else None)

    def _require_postgres(self) -> None:
        if not self.config.db_url.startswith("postgresql"):
            raise RuntimeError(
                "Semantic arXiv search requires PostgreSQL with pgvector enabled. "
                "Set LAB_DB_URL to a PostgreSQL database before using sync or search."
            )

    def _first_non_whitespace(self, path: Path) -> str:
        with path.open("r", encoding="utf-8") as handle:
            while True:
                char = handle.read(1)
                if not char:
                    return ""
                if not char.isspace():
                    return char

    def _iter_json_array(self, path: Path) -> Iterator[dict[str, Any]]:
        decoder = json.JSONDecoder()
        buffer = ""
        eof = False
        with path.open("r", encoding="utf-8") as handle:
            while True:
                if not eof and len(buffer) < 65536:
                    chunk = handle.read(65536)
                    if chunk:
                        buffer += chunk
                    else:
                        eof = True
                idx = 0
                consumed = 0
                while idx < len(buffer):
                    while idx < len(buffer) and buffer[idx].isspace():
                        idx += 1
                    if idx >= len(buffer):
                        break
                    if buffer[idx] in "[,":
                        idx += 1
                        continue
                    if buffer[idx] == "]":
                        return
                    try:
                        value, next_idx = decoder.raw_decode(buffer, idx)
                    except JSONDecodeError:
                        break
                    if isinstance(value, dict):
                        yield value
                    idx = next_idx
                    consumed = idx
                if consumed:
                    buffer = buffer[consumed:]
                if eof:
                    break

    def _parse_snapshot_authors(self, row: dict[str, Any]) -> list[str]:
        parsed = row.get("authors_parsed")
        if isinstance(parsed, list):
            authors: list[str] = []
            for item in parsed:
                if isinstance(item, list):
                    name = " ".join(str(part).strip() for part in item if str(part).strip()).strip()
                    if name:
                        authors.append(name)
            if authors:
                return authors
        authors_field = str(row.get("authors") or "").strip()
        if not authors_field:
            return []
        return [item.strip() for item in authors_field.split(",") if item.strip()]

    def _parse_snapshot_created(self, row: dict[str, Any]) -> datetime | None:
        versions = row.get("versions")
        if isinstance(versions, list) and versions:
            created = versions[0].get("created") if isinstance(versions[0], dict) else None
            parsed = self._parse_datetime(created)
            if parsed is not None:
                return parsed
        return self._parse_datetime(row.get("created"))

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        text_value = str(value).strip()
        if not text_value:
            return None
        normalized = text_value.replace("Z", "+00:00")
        for fmt in (
            None,
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%d",
        ):
            try:
                if fmt is None:
                    parsed = datetime.fromisoformat(normalized)
                else:
                    parsed = datetime.strptime(text_value, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

    def _build_search_text(self, title: str, abstract: str | None) -> str:
        abstract_text = (abstract or "").strip()
        return f"{title.strip()}\n\n{abstract_text}".strip()

    def _content_hash(self, title: str, abstract: str | None) -> str:
        payload = f"{title.strip()}\n\n{(abstract or '').strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _vector_literal(self, vector: list[float]) -> str:
        return "[" + ",".join(f"{float(item):.12g}" for item in vector) + "]"

    def _format_oai_date(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.date().isoformat()

    def _same_value(self, left: Any, right: Any) -> bool:
        if isinstance(left, datetime) and isinstance(right, datetime):
            left_dt = left if left.tzinfo else left.replace(tzinfo=UTC)
            right_dt = right if right.tzinfo else right.replace(tzinfo=UTC)
            return left_dt == right_dt
        return left == right
