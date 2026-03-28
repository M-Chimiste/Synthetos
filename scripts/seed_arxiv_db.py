#!/usr/bin/env python3
"""Seed the arXiv warehouse table from a downloaded Kaggle snapshot.

Reads the arXiv metadata JSON (line-delimited or array format), generates
embeddings with the sentence-transformers model configured in AppConfig
(default: Alibaba-NLP/gte-modernbert-base, 768-dim), and bulk-upserts
records into the ``arxiv_papers`` table in PostgreSQL with pgvector.

Usage examples:

    # Use the default snapshot path from config / LAB_ARXIV_KAGGLE_DATASET
    python scripts/seed_arxiv_db.py

    # Point at an explicit file
    python scripts/seed_arxiv_db.py --snapshot /data/arxiv-metadata-oai-snapshot.json

    # Limit to 10 000 records with a larger embedding batch size
    python scripts/seed_arxiv_db.py --max-records 10000 --embedding-batch-size 64

    # Filter to specific arXiv categories
    python scripts/seed_arxiv_db.py --categories cs.LG,cs.AI,stat.ML

    # Use GPU for embedding generation
    python scripts/seed_arxiv_db.py --device cuda

    # Dry run — parse and count records without touching the database
    python scripts/seed_arxiv_db.py --dry-run
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import structlog
import typer

# ---------------------------------------------------------------------------
# Ensure project root is importable when running as ``python scripts/...``
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from libs.adapters.embeddings import SentenceTransformerEmbeddingAdapter
from libs.core.config import AppConfig, EmbeddingConfig, get_config
from libs.core.ids import generate_public_id
from libs.retrieval.arxiv_warehouse import ArxivWarehouseService
from libs.storage.models import ArxivSyncRunModel
from libs.storage.session import get_session_factory, initialize_database

log = structlog.get_logger(__name__)
app = typer.Typer(help="Seed the arXiv warehouse from a Kaggle snapshot file.")


def _iter_filtered(
    warehouse: ArxivWarehouseService,
    snapshot_path: Path,
    *,
    categories: set[str] | None,
    max_records: int | None,
) -> Iterator[dict[str, Any]]:
    """Yield snapshot rows, optionally filtering by category and capping count."""
    emitted = 0
    for row in warehouse.iter_snapshot_rows(snapshot_path):
        if categories:
            row_cats = set(str(row.get("categories", "")).split())
            if not row_cats.intersection(categories):
                continue
        yield row
        emitted += 1
        if max_records and emitted >= max_records:
            return


@app.command()
def seed(
    snapshot: str | None = typer.Option(
        None,
        "--snapshot",
        "-s",
        help=(
            "Path to the arXiv metadata JSON file. "
            "Defaults to the config's arxiv_snapshot_path "
            "(env: LAB_ARXIV_KAGGLE_DATASET)."
        ),
    ),
    db_url: str | None = typer.Option(
        None,
        "--db-url",
        help="PostgreSQL connection string. Defaults to LAB_DB_URL.",
    ),
    batch_size: int = typer.Option(
        128,
        "--batch-size",
        "-b",
        help="Records per database commit batch.",
    ),
    embedding_batch_size: int = typer.Option(
        16,
        "--embedding-batch-size",
        help="Texts per embedding model forward pass.",
    ),
    max_records: int | None = typer.Option(
        None,
        "--max-records",
        "-n",
        help="Stop after ingesting this many records (useful for testing).",
    ),
    categories: str | None = typer.Option(
        None,
        "--categories",
        "-c",
        help="Comma-separated arXiv categories to include (e.g. cs.LG,cs.AI).",
    ),
    device: str = typer.Option(
        "cpu",
        "--device",
        "-d",
        help="Torch device for the embedding model (cpu, cuda, mps).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and count records without writing to the database.",
    ),
    log_every: int = typer.Option(
        1000,
        "--log-every",
        help="Print a progress line every N records.",
    ),
) -> None:
    """Seed the arXiv warehouse from a downloaded Kaggle snapshot."""
    # ---- config overrides ---------------------------------------------------
    config = _build_config(
        db_url=db_url,
        snapshot=snapshot,
        device=device,
        embedding_batch_size=embedding_batch_size,
    )

    snapshot_path = Path(snapshot) if snapshot else config.arxiv_snapshot_path
    if not snapshot_path.exists():
        typer.echo(f"ERROR: Snapshot file not found: {snapshot_path}", err=True)
        typer.echo(
            "Download the Kaggle arXiv dataset first, or set --snapshot / "
            "LAB_ARXIV_KAGGLE_DATASET.",
            err=True,
        )
        raise typer.Exit(1)

    cat_filter = (
        {cat.strip() for cat in categories.split(",") if cat.strip()}
        if categories
        else None
    )

    typer.echo("=" * 60)
    typer.echo("arXiv Database Seed")
    typer.echo("=" * 60)
    typer.echo(f"  Snapshot:          {snapshot_path}")
    typer.echo(f"  Embedding model:   {config.embedding.model_id}")
    typer.echo(f"  Embedding device:  {config.embedding.device}")
    typer.echo(f"  Batch size:        {batch_size}")
    typer.echo(f"  Embedding batch:   {config.embedding.batch_size}")
    typer.echo(f"  Max records:       {max_records or 'unlimited'}")
    typer.echo(f"  Category filter:   {', '.join(sorted(cat_filter)) if cat_filter else 'none'}")
    typer.echo(f"  Dry run:           {dry_run}")

    # ---- dry run: just count ------------------------------------------------
    if dry_run:
        typer.echo("=" * 60)
        _dry_run(config, snapshot_path, cat_filter, max_records, log_every)
        return

    if not config.db_url.startswith("postgresql"):
        typer.echo(
            "ERROR: A PostgreSQL database with pgvector is required. "
            "Set LAB_DB_URL or --db-url.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"  Database:          {_redact_url(config.db_url)}")
    typer.echo("=" * 60)

    # ---- initialize ---------------------------------------------------------
    initialize_database(config)

    typer.echo("\nWarming up embedding model …")
    embedder = SentenceTransformerEmbeddingAdapter(config.embedding)
    embedder.warmup()
    typer.echo("Embedding model ready.\n")

    warehouse = ArxivWarehouseService(config, embedder=embedder)
    session_factory = get_session_factory(config)

    # Create a sync-run record for tracking
    with session_factory() as session:
        sync_run = ArxivSyncRunModel(
            public_id=generate_public_id("arxivsync"),
            mode="full",
            source="kaggle_seed_script",
            status="running",
        )
        session.add(sync_run)
        session.commit()
        sync_run_id = sync_run.id
        sync_run_public_id = sync_run.public_id

    typer.echo(f"Sync run: {sync_run_public_id}")
    typer.echo("Ingesting records …\n")

    t0 = time.monotonic()
    inserted = 0
    updated = 0
    reembedded = 0
    skipped = 0
    errors = 0
    total_processed = 0

    rows_iter = _iter_filtered(
        warehouse, snapshot_path, categories=cat_filter, max_records=max_records,
    )

    batch: list[Any] = []
    for row in rows_iter:
        try:
            canonical = warehouse._canonicalize_snapshot_row(row)
        except (ValueError, KeyError) as exc:
            errors += 1
            if errors <= 5:
                log.warning("seed_row_skip", error=str(exc))
            continue

        batch.append(canonical)
        if len(batch) >= batch_size:
            stats = _flush_batch(warehouse, session_factory, batch)
            inserted += stats["inserted"]
            updated += stats["updated"]
            reembedded += stats["reembedded"]
            skipped += stats["skipped"]
            total_processed += len(batch)
            batch = []

            if total_processed % log_every < batch_size:
                elapsed = time.monotonic() - t0
                rate = total_processed / elapsed if elapsed > 0 else 0
                typer.echo(
                    f"  [{total_processed:>8,}]  "
                    f"ins={inserted:,}  upd={updated:,}  emb={reembedded:,}  "
                    f"skip={skipped:,}  err={errors:,}  "
                    f"({rate:,.0f} rec/s)"
                )

    # flush remaining
    if batch:
        stats = _flush_batch(warehouse, session_factory, batch)
        inserted += stats["inserted"]
        updated += stats["updated"]
        reembedded += stats["reembedded"]
        skipped += stats["skipped"]
        total_processed += len(batch)

    elapsed = time.monotonic() - t0

    # Update sync-run record
    with session_factory() as session:
        sync_run = session.get(ArxivSyncRunModel, sync_run_id)
        if sync_run:
            sync_run.status = "completed"
            sync_run.inserted_count = inserted
            sync_run.updated_count = updated
            sync_run.reembedded_count = reembedded
            sync_run.skipped_count = skipped
            session.commit()

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("Seed complete")
    typer.echo("=" * 60)
    typer.echo(f"  Total processed:   {total_processed:,}")
    typer.echo(f"  Inserted:          {inserted:,}")
    typer.echo(f"  Updated:           {updated:,}")
    typer.echo(f"  Embedded:          {reembedded:,}")
    typer.echo(f"  Skipped:           {skipped:,}")
    typer.echo(f"  Parse errors:      {errors:,}")
    typer.echo(f"  Elapsed:           {elapsed:.1f}s")
    if total_processed > 0 and elapsed > 0:
        typer.echo(f"  Throughput:        {total_processed / elapsed:,.0f} rec/s")
    typer.echo(f"  Sync run ID:       {sync_run_public_id}")
    typer.echo("=" * 60)


def _flush_batch(
    warehouse: ArxivWarehouseService,
    session_factory: Any,
    batch: list[Any],
) -> dict[str, Any]:
    """Upsert a batch of canonical papers within a session."""
    with session_factory() as session:
        stats = warehouse._upsert_batch(session, batch)
        session.commit()
        return stats


def _dry_run(
    config: AppConfig,
    snapshot_path: Path,
    cat_filter: set[str] | None,
    max_records: int | None,
    log_every: int,
) -> None:
    """Count records without touching the database."""
    typer.echo("\nDry run — counting records …\n")

    # Minimal warehouse instance (embedder unused in dry-run path)
    class _Stub:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return []
        def embed_query(self, text: str) -> list[float]:
            return []

    warehouse = ArxivWarehouseService(config, embedder=_Stub())  # type: ignore[arg-type]
    count = 0
    parse_errors = 0
    t0 = time.monotonic()
    for row in _iter_filtered(
        warehouse, snapshot_path, categories=cat_filter, max_records=max_records,
    ):
        try:
            warehouse._canonicalize_snapshot_row(row)
            count += 1
        except (ValueError, KeyError):
            parse_errors += 1
        if (count + parse_errors) % log_every == 0:
            typer.echo(f"  Scanned {count + parse_errors:,} rows ({count:,} valid) …")
    elapsed = time.monotonic() - t0
    typer.echo(
        f"\nDry run result: {count:,} valid records, "
        f"{parse_errors:,} parse errors, {elapsed:.1f}s elapsed."
    )


def _build_config(
    *,
    db_url: str | None,
    snapshot: str | None,
    device: str,
    embedding_batch_size: int,
) -> AppConfig:
    """Build an AppConfig with CLI overrides applied."""
    if db_url:
        os.environ["LAB_DB_URL"] = db_url
    if snapshot:
        os.environ["LAB_ARXIV_KAGGLE_DATASET"] = snapshot

    # Clear cached config so overrides take effect
    get_config.cache_clear()
    config = get_config()

    # Override embedding settings from CLI flags
    config._embedding = EmbeddingConfig(
        provider=config.embedding.provider,
        model_id=config.embedding.model_id,
        dimension=config.embedding.dimension,
        batch_size=embedding_batch_size,
        device=device,
        normalize=config.embedding.normalize,
    )
    return config


def _redact_url(url: str) -> str:
    """Redact password from a database URL for display."""
    if "@" in url:
        scheme_user, _, host_rest = url.rpartition("@")
        if ":" in scheme_user:
            parts = scheme_user.rsplit(":", 1)
            return f"{parts[0]}:***@{host_rest}"
    return url


if __name__ == "__main__":
    app()
