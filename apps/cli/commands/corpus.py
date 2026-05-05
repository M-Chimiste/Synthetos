"""Corpus management CLI commands.

The headline command is ``synthetos corpus import-arxiv`` which streams a
JSONL dump of pre-embedded arXiv records into the ``arxiv_corpus`` table.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import orjson
import psycopg
import typer
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from uuid_utils import uuid7

from libs.adapters.embeddings.router import EXPECTED_DIMENSION, EmbeddingsRouter
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.storage.base import get_sync_session_factory
from libs.storage.models.corpus import ArxivCorpusRecord, CorpusImportRun

app = typer.Typer(help="Manage the local arXiv corpus mirror.")

log = get_logger("cli.corpus")


_EXPECTED_FORMAT = "synthetos.arxiv.embedded.v1"
_EXPECTED_MODEL = "Alibaba-NLP/gte-modernbert-base"
_DEFAULT_BATCH_SIZE = 500
_CHECKPOINT_INTERVAL = 5_000
_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_PAGE_SIZE = 1000
_ARXIV_MIN_REQUEST_INTERVAL_S = 3.0
_ARXIV_DEFAULT_WINDOW_DAYS = 1
_ARXIV_MAX_RETRIES = 3
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _psycopg_dsn() -> str:
    return get_settings().sync_db_url.replace("postgresql+psycopg://", "postgresql://")


def _format_pgvector_literal(vec: list[float] | None) -> str | None:
    if vec is None:
        return None
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    cleaned = arxiv_id.strip().lower()
    cleaned = cleaned.removeprefix("arxiv:")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    return cleaned or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_arxiv_api_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M")


def _build_incremental_search_query(start: datetime, end: datetime) -> str:
    return (
        f"submittedDate:[{_format_arxiv_api_date(start)} "
        f"TO {_format_arxiv_api_date(end)}]"
    )


def _entry_text(entry: ET.Element, tag: str, *, ns: str = "atom") -> str | None:
    el = entry.find(f"{ns}:{tag}", _ATOM_NS)
    if el is None or el.text is None:
        return None
    return " ".join(el.text.split()).strip() or None


def _entry_datetime(entry: ET.Element, tag: str) -> str | None:
    parsed = _parse_datetime(_entry_text(entry, tag))
    return parsed.isoformat() if parsed is not None else None


def _arxiv_record_from_entry(entry: ET.Element) -> dict[str, Any] | None:
    raw_id = _entry_text(entry, "id")
    if not raw_id:
        return None
    arxiv_id = _normalize_arxiv_id(raw_id.rsplit("/", 1)[-1])
    if not arxiv_id:
        return None

    title = _entry_text(entry, "title") or ""
    abstract = _entry_text(entry, "summary") or ""
    authors: list[str] = []
    for author_el in entry.findall("atom:author", _ATOM_NS):
        name = _entry_text(author_el, "name")
        if name:
            authors.append(name)

    categories: list[str] = []
    primary_category: str | None = None
    primary_el = entry.find("arxiv:primary_category", _ATOM_NS)
    if primary_el is not None:
        primary_category = primary_el.get("term")
    for cat_el in entry.findall("atom:category", _ATOM_NS):
        term = cat_el.get("term")
        if term:
            categories.append(term)

    source_url = raw_id
    pdf_url: str | None = None
    for link_el in entry.findall("atom:link", _ATOM_NS):
        href = link_el.get("href")
        if not href:
            continue
        if link_el.get("title") == "pdf":
            pdf_url = href
        elif link_el.get("rel") == "alternate":
            source_url = href

    created_date = _entry_datetime(entry, "published")
    updated_date = _entry_datetime(entry, "updated")
    doi = _entry_text(entry, "doi", ns="arxiv")
    journal_ref = _entry_text(entry, "journal_ref", ns="arxiv")
    comment = _entry_text(entry, "comment", ns="arxiv")
    search_text = "\n\n".join(part for part in [title, abstract] if part)
    hash_payload = {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "categories": categories,
        "created_date": created_date,
        "updated_date": updated_date,
    }
    content_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "categories": categories,
        "created_date": created_date,
        "updated_date": updated_date,
        "doi": doi,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "raw_metadata": {
            "source": "arxiv_live",
            "raw_id": raw_id,
            "primary_category": primary_category,
            "journal_ref": journal_ref,
            "comment": comment,
        },
        "search_text": search_text,
        "content_hash": content_hash,
        "embedding": None,
        "embedding_model_id": _EXPECTED_MODEL,
        "embedding_updated_at": None,
        "imported_at": utcnow(),
    }


def _parse_arxiv_incremental_feed(payload: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        record = _arxiv_record_from_entry(entry)
        if record is not None:
            records.append(record)
    return records


def _latest_corpus_created_at(session) -> datetime | None:
    latest = session.execute(
        select(func.max(ArxivCorpusRecord.created_date)).where(
            ArxivCorpusRecord.created_date.isnot(None)
        )
    ).scalar_one()
    return _parse_datetime(latest)


async def _fetch_arxiv_incremental_page(
    client: httpx.AsyncClient,
    *,
    start: datetime,
    end: datetime,
    offset: int,
    page_size: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search_query": _build_incremental_search_query(start, end),
        "start": offset,
        "max_results": page_size,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    last_response: httpx.Response | None = None
    for attempt in range(1, _ARXIV_MAX_RETRIES + 1):
        response = await client.get(_ARXIV_API_URL, params=params)
        last_response = response
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return _parse_arxiv_incremental_feed(response.content)
        if attempt < _ARXIV_MAX_RETRIES:
            await asyncio.sleep(float(2**attempt))
    assert last_response is not None
    last_response.raise_for_status()
    return []


async def _fetch_arxiv_incremental_records(
    *,
    start: datetime,
    end: datetime,
    page_size: int,
    limit: int | None,
    rate_limit_seconds: float,
    window_days: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    window_delta = timedelta(days=window_days)
    async with httpx.AsyncClient(timeout=60.0) as client:
        window_start = start
        while window_start < end:
            window_end = min(window_start + window_delta, end)
            offset = 0
            while True:
                page = await _fetch_arxiv_incremental_page(
                    client,
                    start=window_start,
                    end=window_end,
                    offset=offset,
                    page_size=page_size,
                )
                if not page:
                    break
                records.extend(page)
                if limit is not None and len(records) >= limit:
                    return records[:limit]
                if len(page) < page_size:
                    break
                offset += len(page)
                if rate_limit_seconds > 0:
                    await asyncio.sleep(rate_limit_seconds)
            window_start = window_end
            if window_start < end and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)
    return records


async def _embed_incremental_records(
    records: list[dict[str, Any]],
    *,
    batch_size: int,
) -> None:
    router = EmbeddingsRouter()
    try:
        for offset in range(0, len(records), batch_size):
            batch = records[offset : offset + batch_size]
            texts = [record["search_text"] or record["title"] for record in batch]
            embeddings = await router.embed(texts)
            if len(embeddings) != len(batch):
                raise RuntimeError(
                    f"Embedding service returned {len(embeddings)} vectors for {len(batch)} texts"
                )
            embedded_at = utcnow().isoformat()
            for record, embedding in zip(batch, embeddings, strict=True):
                if len(embedding) != EXPECTED_DIMENSION:
                    raise RuntimeError(
                        f"Embedding for {record['arxiv_id']} has dimension {len(embedding)}, "
                        f"expected {EXPECTED_DIMENSION}"
                    )
                record["embedding"] = embedding
                record["embedding_updated_at"] = embedded_at
    finally:
        await router.close()


def _embed_incremental_records_sentence_transformers(
    records: list[dict[str, Any]],
    *,
    batch_size: int,
    device: str | None,
) -> None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. Run with "
            "`uv run --extra reranker synthetos corpus update-arxiv-live ...`."
        ) from exc

    kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "config_kwargs": {"reference_compile": False},
        "model_kwargs": {"attn_implementation": "sdpa"},
    }
    if device:
        kwargs["device"] = device
    model = SentenceTransformer(_EXPECTED_MODEL, **kwargs)

    texts = [record["search_text"] or record["title"] for record in records]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    embedded_at = utcnow().isoformat()
    for record, embedding in zip(records, embeddings, strict=True):
        vector = [float(value) for value in embedding]
        if len(vector) != EXPECTED_DIMENSION:
            raise RuntimeError(
                f"Embedding for {record['arxiv_id']} has dimension {len(vector)}, "
                f"expected {EXPECTED_DIMENSION}"
            )
        record["embedding"] = vector
        record["embedding_updated_at"] = embedded_at


def _coerce_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    fmt = raw.get("_synthetos_format")
    if fmt and fmt != _EXPECTED_FORMAT:
        log.warning("corpus.unknown_format", got=fmt)
        return None
    embedding_model = raw.get("embedding_model_id")
    if embedding_model and embedding_model != _EXPECTED_MODEL:
        log.warning(
            "corpus.unexpected_embedding_model",
            got=embedding_model,
            expected=_EXPECTED_MODEL,
        )
        return None

    arxiv_id = raw.get("arxiv_id")
    if not arxiv_id:
        return None

    embedding = raw.get("embedding")
    if embedding is not None and len(embedding) != 768:
        log.warning("corpus.bad_dimension", arxiv_id=arxiv_id, dim=len(embedding))
        return None

    return {
        "arxiv_id": str(arxiv_id),
        "title": raw.get("title") or "",
        "abstract": raw.get("abstract") or "",
        "authors": raw.get("authors"),
        "categories": raw.get("categories"),
        "created_date": raw.get("created_date"),
        "updated_date": raw.get("updated_date"),
        "doi": raw.get("doi") or None,
        "source_url": raw.get("source_url") or None,
        "pdf_url": raw.get("pdf_url") or None,
        "raw_metadata": raw.get("raw_metadata"),
        "search_text": raw.get("search_text"),
        "content_hash": raw.get("content_hash"),
        "embedding": embedding,
        "embedding_model_id": embedding_model,
        "embedding_updated_at": raw.get("embedding_updated_at"),
        "imported_at": utcnow(),
    }


def _flush_batch(session, batch: list[dict[str, Any]], *, on_conflict_update: bool) -> None:
    if not batch:
        return
    stmt = pg_insert(ArxivCorpusRecord).values(batch)
    if on_conflict_update:
        excluded = {
            col: stmt.excluded[col]
            for col in [
                "title",
                "abstract",
                "authors",
                "categories",
                "created_date",
                "updated_date",
                "doi",
                "source_url",
                "pdf_url",
                "raw_metadata",
                "search_text",
                "content_hash",
                "embedding",
                "embedding_model_id",
                "embedding_updated_at",
                "imported_at",
            ]
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["arxiv_id"],
            set_=excluded,
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["arxiv_id"])
    session.execute(stmt)
    session.commit()


def _copy_batch(conn: psycopg.Connection[Any], batch: list[dict[str, Any]]) -> int:
    if not batch:
        return 0

    with conn.cursor() as cur:
        with cur.copy(
            """
            COPY arxiv_corpus_import_stage (
                arxiv_id,
                title,
                abstract,
                authors_json,
                categories_json,
                created_date,
                updated_date,
                doi,
                source_url,
                pdf_url,
                raw_metadata_json,
                search_text,
                content_hash,
                embedding_text,
                embedding_model_id,
                embedding_updated_at,
                imported_at
            ) FROM STDIN
            """
        ) as copy:
            for record in batch:
                copy.write_row(
                    (
                        record["arxiv_id"],
                        record["title"],
                        record["abstract"],
                        json.dumps(record["authors"]) if record["authors"] is not None else None,
                        json.dumps(record["categories"])
                        if record["categories"] is not None
                        else None,
                        record["created_date"],
                        record["updated_date"],
                        record["doi"],
                        record["source_url"],
                        record["pdf_url"],
                        json.dumps(record["raw_metadata"])
                        if record["raw_metadata"] is not None
                        else None,
                        record["search_text"],
                        record["content_hash"],
                        _format_pgvector_literal(record["embedding"]),
                        record["embedding_model_id"],
                        record["embedding_updated_at"],
                        record["imported_at"],
                    )
                )

        cur.execute(
            """
            INSERT INTO arxiv_corpus (
                arxiv_id,
                title,
                abstract,
                authors,
                categories,
                created_date,
                updated_date,
                doi,
                source_url,
                pdf_url,
                raw_metadata,
                search_text,
                content_hash,
                embedding,
                embedding_model_id,
                embedding_updated_at,
                imported_at
            )
            SELECT
                arxiv_id,
                title,
                abstract,
                CASE WHEN authors_json IS NULL THEN NULL ELSE authors_json::jsonb END,
                CASE WHEN categories_json IS NULL THEN NULL ELSE categories_json::jsonb END,
                created_date,
                updated_date,
                doi,
                source_url,
                pdf_url,
                CASE
                    WHEN raw_metadata_json IS NULL THEN NULL
                    ELSE raw_metadata_json::jsonb
                END,
                search_text,
                content_hash,
                CASE
                    WHEN embedding_text IS NULL THEN NULL
                    ELSE CAST(embedding_text AS vector)
                END,
                embedding_model_id,
                embedding_updated_at,
                imported_at::timestamp
            FROM arxiv_corpus_import_stage
            ON CONFLICT (arxiv_id) DO NOTHING
            """
        )
        inserted = cur.rowcount or 0
    conn.commit()
    return inserted


def _ensure_copy_stage(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS arxiv_corpus_import_stage (
                arxiv_id text,
                title text,
                abstract text,
                authors_json text,
                categories_json text,
                created_date text,
                updated_date text,
                doi text,
                source_url text,
                pdf_url text,
                raw_metadata_json text,
                search_text text,
                content_hash text,
                embedding_text text,
                embedding_model_id text,
                embedding_updated_at text,
                imported_at timestamptz
            ) ON COMMIT DELETE ROWS
            """
        )
    conn.commit()


def _create_run(session, *, source_path: Path, mode: str) -> CorpusImportRun:
    run = CorpusImportRun(
        id=uuid7(),
        source_path=str(source_path.resolve()),
        mode=mode,
        status="running",
        last_line=0,
        last_arxiv_id=None,
        inserted_count=0,
        skipped_count=0,
        rejected_count=0,
        started_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(run)
    session.commit()
    return run


def _load_resume_run(session, *, source_path: Path) -> CorpusImportRun | None:
    result = session.execute(
        select(CorpusImportRun)
        .where(
            CorpusImportRun.source_path == str(source_path.resolve()),
            CorpusImportRun.completed_at.is_(None),
        )
        .order_by(desc(CorpusImportRun.started_at))
    )
    return result.scalars().first()


def _checkpoint_run(
    session,
    *,
    run_id,
    line_no: int,
    last_arxiv_id: str | None,
    inserted: int,
    skipped: int,
    rejected: int,
    status: str = "running",
    completed: bool = False,
) -> None:
    run = session.get(CorpusImportRun, run_id)
    if run is None:
        return
    run.last_line = line_no
    run.last_arxiv_id = last_arxiv_id
    run.inserted_count = inserted
    run.skipped_count = skipped
    run.rejected_count = rejected
    run.status = status
    run.updated_at = utcnow()
    if completed:
        run.completed_at = utcnow()
    session.commit()


@app.command("import-arxiv")
def import_arxiv(
    path: Path = typer.Option(
        Path("artifacts/arxiv-embedded.jsonl"),
        "--path",
        help="JSONL dump path",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Stop after N records"),
    batch_size: int = typer.Option(_DEFAULT_BATCH_SIZE, "--batch-size"),
    resume: bool = typer.Option(
        False,
        "--resume/--no-resume",
        help="Resume an interrupted import using DB-tracked checkpoints and upserts",
    ),
) -> None:
    """Stream a JSONL dump of pre-embedded arXiv records into ``arxiv_corpus``.

    The HNSW + GIN indexes are managed by the migration. After a fresh
    import you may want to run ``REINDEX INDEX CONCURRENTLY ix_arxiv_corpus_embedding;``
    to compact the HNSW graph.
    """
    if not path.exists():
        typer.echo(f"JSONL not found at {path}", err=True)
        raise typer.Exit(code=1)

    factory = get_sync_session_factory()

    inserted = 0
    skipped = 0
    rejected = 0
    processed_valid = 0
    current_line_no = 0
    current_last_arxiv_id: str | None = None

    with factory() as session:
        run = (
            _load_resume_run(session, source_path=path)
            if resume
            else None
        )
        if run is None:
            run = _create_run(session, source_path=path, mode="upsert" if resume else "copy")
        else:
            typer.echo(
                f"Resuming run {run.id} from line {run.last_line} "
                f"(inserted={run.inserted_count}, rejected={run.rejected_count})"
            )
            inserted = run.inserted_count
            skipped = run.skipped_count
            rejected = run.rejected_count
            current_line_no = run.last_line
            current_last_arxiv_id = run.last_arxiv_id

    typer.echo(
        f"Importing from {path} (mode={run.mode}, limit={limit or '∞'}, batch_size={batch_size})"
    )

    try:
        if resume:
            with factory() as session:
                batch: list[dict[str, Any]] = []
                with path.open("rb") as fh:
                    for line_no, raw_line in enumerate(fh, start=1):
                        if line_no <= run.last_line:
                            continue
                        current_line_no = line_no
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            raw = orjson.loads(raw_line)
                        except orjson.JSONDecodeError:
                            rejected += 1
                            if line_no % _CHECKPOINT_INTERVAL == 0:
                                _checkpoint_run(
                                    session,
                                    run_id=run.id,
                                    line_no=line_no,
                                    last_arxiv_id=current_last_arxiv_id,
                                    inserted=inserted,
                                    skipped=skipped,
                                    rejected=rejected,
                                )
                            continue

                        record = _coerce_record(raw)
                        if record is None:
                            rejected += 1
                            if line_no % _CHECKPOINT_INTERVAL == 0:
                                _checkpoint_run(
                                    session,
                                    run_id=run.id,
                                    line_no=line_no,
                                    last_arxiv_id=current_last_arxiv_id,
                                    inserted=inserted,
                                    skipped=skipped,
                                    rejected=rejected,
                                )
                            continue

                        batch.append(record)
                        processed_valid += 1
                        current_last_arxiv_id = record["arxiv_id"]
                        if len(batch) >= batch_size:
                            _flush_batch(session, batch, on_conflict_update=True)
                            inserted += len(batch)
                            _checkpoint_run(
                                session,
                                run_id=run.id,
                                line_no=line_no,
                                last_arxiv_id=current_last_arxiv_id,
                                inserted=inserted,
                                skipped=skipped,
                                rejected=rejected,
                            )
                            batch.clear()
                            if inserted % (batch_size * 10) == 0:
                                typer.echo(
                                    f"  imported={inserted:>10}  skipped={skipped:>8}  "
                                    f"rejected={rejected:>6}  line={line_no}"
                                )

                        if limit is not None and processed_valid >= limit:
                            break

                if batch:
                    _flush_batch(session, batch, on_conflict_update=True)
                    inserted += len(batch)
                    _checkpoint_run(
                        session,
                        run_id=run.id,
                        line_no=current_line_no,
                        last_arxiv_id=current_last_arxiv_id,
                        inserted=inserted,
                        skipped=skipped,
                        rejected=rejected,
                    )
        else:
            with psycopg.connect(_psycopg_dsn()) as conn:
                _ensure_copy_stage(conn)
                batch = []
                with path.open("rb") as fh:
                    for line_no, raw_line in enumerate(fh, start=1):
                        current_line_no = line_no
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            raw = orjson.loads(raw_line)
                        except orjson.JSONDecodeError:
                            rejected += 1
                            if line_no % _CHECKPOINT_INTERVAL == 0:
                                with factory() as session:
                                    _checkpoint_run(
                                        session,
                                        run_id=run.id,
                                        line_no=line_no,
                                        last_arxiv_id=current_last_arxiv_id,
                                        inserted=inserted,
                                        skipped=skipped,
                                        rejected=rejected,
                                    )
                            continue

                        record = _coerce_record(raw)
                        if record is None:
                            rejected += 1
                            if line_no % _CHECKPOINT_INTERVAL == 0:
                                with factory() as session:
                                    _checkpoint_run(
                                        session,
                                        run_id=run.id,
                                        line_no=line_no,
                                        last_arxiv_id=current_last_arxiv_id,
                                        inserted=inserted,
                                        skipped=skipped,
                                        rejected=rejected,
                                    )
                            continue

                        batch.append(record)
                        processed_valid += 1
                        current_last_arxiv_id = record["arxiv_id"]
                        if len(batch) >= batch_size:
                            inserted += _copy_batch(conn, batch)
                            with factory() as session:
                                _checkpoint_run(
                                    session,
                                    run_id=run.id,
                                    line_no=line_no,
                                    last_arxiv_id=current_last_arxiv_id,
                                    inserted=inserted,
                                    skipped=skipped,
                                    rejected=rejected,
                                )
                            batch.clear()
                            if inserted % (batch_size * 10) == 0:
                                typer.echo(
                                    f"  imported={inserted:>10}  skipped={skipped:>8}  "
                                    f"rejected={rejected:>6}  line={line_no}"
                                )

                        if limit is not None and processed_valid >= limit:
                            break

                if batch:
                    inserted += _copy_batch(conn, batch)
                    with factory() as session:
                        _checkpoint_run(
                            session,
                            run_id=run.id,
                            line_no=current_line_no,
                            last_arxiv_id=current_last_arxiv_id,
                            inserted=inserted,
                            skipped=skipped,
                            rejected=rejected,
                        )
    except Exception:
        with factory() as session:
            _checkpoint_run(
                session,
                run_id=run.id,
                line_no=current_line_no,
                last_arxiv_id=current_last_arxiv_id,
                inserted=inserted,
                skipped=skipped,
                rejected=rejected,
                status="failed",
            )
        raise

    with factory() as session:
        _checkpoint_run(
            session,
            run_id=run.id,
            line_no=current_line_no,
            last_arxiv_id=current_last_arxiv_id,
            inserted=inserted,
            skipped=skipped,
            rejected=rejected,
            status="completed",
            completed=True,
        )
        total = session.execute(select(func.count()).select_from(ArxivCorpusRecord)).scalar_one()

    typer.echo(
        f"Done. inserted={inserted}  skipped={skipped}  rejected={rejected}  table_total={total}"
    )


@app.command("update-arxiv-live")
def update_arxiv_live(
    start_date: str | None = typer.Option(
        None,
        "--start-date",
        help="UTC ISO timestamp to start from; defaults to max arxiv_corpus.created_date",
    ),
    end_date: str | None = typer.Option(
        None,
        "--end-date",
        help="UTC ISO timestamp to end at; defaults to current UTC time",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Stop after N fetched records"),
    page_size: int = typer.Option(
        _ARXIV_PAGE_SIZE,
        "--page-size",
        min=1,
        max=2000,
        help="arXiv API page size",
    ),
    embed_batch_size: int = typer.Option(
        64,
        "--embed-batch-size",
        min=1,
        help="Embedding request batch size",
    ),
    embedding_backend: str = typer.Option(
        "sentence-transformers",
        "--embedding-backend",
        help="Embedding backend: sentence-transformers or router",
    ),
    embedding_device: str | None = typer.Option(
        "cuda",
        "--embedding-device",
        help="Sentence-transformers device, e.g. cpu or cuda",
    ),
    upsert_batch_size: int = typer.Option(
        200,
        "--upsert-batch-size",
        min=1,
        help="Database upsert batch size",
    ),
    rate_limit_seconds: float = typer.Option(
        _ARXIV_MIN_REQUEST_INTERVAL_S,
        "--rate-limit-seconds",
        min=0.0,
        help="Delay between arXiv API pages",
    ),
    window_days: int = typer.Option(
        _ARXIV_DEFAULT_WINDOW_DAYS,
        "--window-days",
        min=1,
        help="Submitted-date window size for each arXiv API scan",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Fetch and summarize without embedding or writing rows",
    ),
) -> None:
    """Fetch new arXiv abstracts across all categories, embed them, and upsert the corpus."""
    factory = get_sync_session_factory()
    with factory() as session:
        latest = _latest_corpus_created_at(session)
        before_total = session.execute(
            select(func.count()).select_from(ArxivCorpusRecord)
        ).scalar_one()

    start = _parse_datetime(start_date) if start_date else latest
    if start is None:
        typer.echo(
            "No corpus created_date found; pass --start-date for the first live update.",
            err=True,
        )
        raise typer.Exit(code=1)

    end = _parse_datetime(end_date) if end_date else utcnow()
    if end is None:
        typer.echo(f"Could not parse --end-date: {end_date}", err=True)
        raise typer.Exit(code=1)
    if start >= end:
        typer.echo(
            f"No update needed: start_date {start.isoformat()} is not before "
            f"end_date {end.isoformat()}."
        )
        return

    typer.echo(
        "Fetching arXiv submitted-date window "
        f"{start.isoformat()} -> {end.isoformat()} across all categories "
        f"(page_size={page_size}, window_days={window_days}, limit={limit or '∞'})"
    )

    run_id = uuid7()
    source_path = (
        "arxiv_live:"
        f"submittedDate[{_format_arxiv_api_date(start)} TO {_format_arxiv_api_date(end)}]"
    )
    with factory() as session:
        run = CorpusImportRun(
            id=run_id,
            source_path=source_path,
            mode="arxiv_live",
            status="running",
            last_line=0,
            last_arxiv_id=None,
            inserted_count=0,
            skipped_count=0,
            rejected_count=0,
            started_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(run)
        session.commit()

    fetched = 0
    upserted = 0
    last_arxiv_id: str | None = None
    started = time.monotonic()
    try:
        records = asyncio.run(
            _fetch_arxiv_incremental_records(
                start=start,
                end=end,
                page_size=page_size,
                limit=limit,
                rate_limit_seconds=rate_limit_seconds,
                window_days=window_days,
            )
        )
        fetched = len(records)
        unique_records = list({record["arxiv_id"]: record for record in records}.values())
        skipped_duplicates = fetched - len(unique_records)
        if unique_records:
            last_arxiv_id = unique_records[-1]["arxiv_id"]

        typer.echo(
            f"Fetched {fetched} records ({len(unique_records)} unique, "
            f"{skipped_duplicates} duplicate ids)."
        )
        if dry_run or not unique_records:
            with factory() as session:
                _checkpoint_run(
                    session,
                    run_id=run_id,
                    line_no=fetched,
                    last_arxiv_id=last_arxiv_id,
                    inserted=0,
                    skipped=skipped_duplicates,
                    rejected=0,
                    status="completed",
                    completed=True,
                )
            suffix = "dry run" if dry_run else "nothing to upsert"
            typer.echo(f"Done ({suffix}).")
            return

        typer.echo(
            f"Embedding {len(unique_records)} records "
            f"(backend={embedding_backend}, embed_batch_size={embed_batch_size})"
        )
        if embedding_backend == "sentence-transformers":
            _embed_incremental_records_sentence_transformers(
                unique_records,
                batch_size=embed_batch_size,
                device=embedding_device,
            )
        elif embedding_backend == "router":
            asyncio.run(
                _embed_incremental_records(unique_records, batch_size=embed_batch_size)
            )
        else:
            raise typer.BadParameter(
                "embedding_backend must be 'sentence-transformers' or 'router'"
            )

        with factory() as session:
            for offset in range(0, len(unique_records), upsert_batch_size):
                batch = unique_records[offset : offset + upsert_batch_size]
                _flush_batch(session, batch, on_conflict_update=True)
                upserted += len(batch)
                last_arxiv_id = batch[-1]["arxiv_id"]
                _checkpoint_run(
                    session,
                    run_id=run_id,
                    line_no=fetched,
                    last_arxiv_id=last_arxiv_id,
                    inserted=upserted,
                    skipped=skipped_duplicates,
                    rejected=0,
                )
                if upserted % (upsert_batch_size * 10) == 0:
                    typer.echo(f"  upserted={upserted:>8} / {len(unique_records)}")

            after_total = session.execute(
                select(func.count()).select_from(ArxivCorpusRecord)
            ).scalar_one()
            _checkpoint_run(
                session,
                run_id=run_id,
                line_no=fetched,
                last_arxiv_id=last_arxiv_id,
                inserted=upserted,
                skipped=skipped_duplicates,
                rejected=0,
                status="completed",
                completed=True,
            )
    except Exception:
        with factory() as session:
            _checkpoint_run(
                session,
                run_id=run_id,
                line_no=fetched,
                last_arxiv_id=last_arxiv_id,
                inserted=upserted,
                skipped=0,
                rejected=0,
                status="failed",
            )
        raise

    elapsed = time.monotonic() - started
    typer.echo(
        f"Done. fetched={fetched}  upserted={upserted}  "
        f"new_rows={after_total - before_total}  table_total={after_total}  "
        f"elapsed={elapsed:.1f}s"
    )


@app.command("stats")
def stats() -> None:
    """Show row counts and basic stats for the arxiv_corpus table."""
    factory = get_sync_session_factory()
    with factory() as session:
        total = session.execute(select(func.count()).select_from(ArxivCorpusRecord)).scalar_one()
        with_embedding = session.execute(
            select(func.count())
            .select_from(ArxivCorpusRecord)
            .where(ArxivCorpusRecord.embedding.isnot(None))
        ).scalar_one()
    typer.echo(f"arxiv_corpus rows:           {total}")
    typer.echo(f"  with embedding:           {with_embedding}")


@app.command("inspect")
def inspect(
    path: Path = typer.Argument(..., help="JSONL dump path"),
    n: int = typer.Option(3, "--n", help="Number of records to read"),
) -> None:
    """Print the first ``n`` records of a JSONL dump for sanity checking."""
    if not path.exists():
        typer.echo(f"JSONL not found at {path}", err=True)
        raise typer.Exit(code=1)
    with path.open("rb") as fh:
        for idx, line in enumerate(fh):
            if idx >= n:
                break
            raw = orjson.loads(line)
            preview = {
                k: (f"<list len={len(v)}>" if isinstance(v, list) and len(v) > 6 else v)
                for k, v in raw.items()
                if k != "embedding"
            }
            preview["embedding"] = f"<vec len={len(raw.get('embedding') or [])}>"
            typer.echo(json.dumps(preview, indent=2, default=str))
