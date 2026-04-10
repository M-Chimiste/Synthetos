"""Corpus management CLI commands.

The headline command is ``synthetos corpus import-arxiv`` which streams a
JSONL dump of pre-embedded arXiv records into the ``arxiv_corpus`` table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orjson
import psycopg
import typer
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from uuid_utils import uuid7

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


def _psycopg_dsn() -> str:
    return get_settings().sync_db_url.replace("postgresql+psycopg://", "postgresql://")


def _format_pgvector_literal(vec: list[float] | None) -> str | None:
    if vec is None:
        return None
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


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
