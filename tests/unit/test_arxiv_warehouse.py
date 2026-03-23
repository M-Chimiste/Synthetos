from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.adapters.literature import RawPaperRecord
from libs.core.config import AppConfig
from libs.retrieval.arxiv_warehouse import ArxivWarehouseService
from libs.storage.base import Base
from libs.storage.models import ArxivPaperModel, ArxivSyncRunModel


class FakeEmbedder:
    def __init__(self):
        self.document_calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [[float(index + 1), float(len(text))] for index, text in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, float(len(text))]


class WarehouseServiceForTest(ArxivWarehouseService):
    def _require_postgres(self) -> None:
        return


def _build_config(tmp_path: Path) -> AppConfig:
    config = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'warehouse.db'}",
        data_root=tmp_path / "data",
        auto_init_db=False,
    )
    config.ensure_data_dirs()
    return config


def _build_session(tmp_path: Path) -> Session:
    config = _build_config(tmp_path)
    engine = create_engine(config.db_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _record(arxiv_id: str, *, abstract: str = "Abstract") -> RawPaperRecord:
    return RawPaperRecord(
        external_id=arxiv_id,
        title=f"Paper {arxiv_id}",
        abstract=abstract,
        authors=["Alice Smith"],
        categories=["cs.LG"],
        publication_date="2024-01-01",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        source_type="arxiv",
        metadata_extra={"updated": "2024-01-02", "doi": f"10.1000/{arxiv_id}"},
    )


def test_iter_snapshot_rows_supports_jsonl_and_array(tmp_path: Path):
    config = _build_config(tmp_path)
    service = WarehouseServiceForTest(config, embedder=FakeEmbedder())

    jsonl_path = tmp_path / "snapshot.jsonl"
    jsonl_path.write_text('{"id":"1","title":"One","abstract":"A"}\n{"id":"2","title":"Two"}\n')
    assert [row["id"] for row in service.iter_snapshot_rows(jsonl_path)] == ["1", "2"]

    array_path = tmp_path / "snapshot-array.json"
    array_path.write_text('[{"id":"3","title":"Three"},{"id":"4","title":"Four"}]')
    assert [row["id"] for row in service.iter_snapshot_rows(array_path)] == ["3", "4"]


def test_upsert_records_deduplicates_and_reembeds_on_text_change(tmp_path: Path):
    session = _build_session(tmp_path)
    config = _build_config(tmp_path)
    embedder = FakeEmbedder()
    service = WarehouseServiceForTest(config, embedder=embedder)

    stats = service._upsert_records(session, iter([service._canonicalize_raw_record(_record("2401.00001"))]))
    session.commit()
    assert stats["inserted"] == 1
    assert stats["reembedded"] == 1

    repeat_stats = service._upsert_records(
        session,
        iter([service._canonicalize_raw_record(_record("2401.00001"))]),
    )
    session.commit()
    assert repeat_stats["inserted"] == 0
    assert repeat_stats["updated"] == 0
    assert repeat_stats["reembedded"] == 0
    assert repeat_stats["skipped"] == 1

    changed_stats = service._upsert_records(
        session,
        iter([service._canonicalize_raw_record(_record("2401.00001", abstract="Changed abstract"))]),
    )
    session.commit()
    assert changed_stats["updated"] == 1
    assert changed_stats["reembedded"] == 1

    stored = session.query(ArxivPaperModel).filter_by(arxiv_id="2401.00001").one()
    assert stored.abstract == "Changed abstract"
    assert stored.embedding_model_id == config.embedding.model_id
    assert len(embedder.document_calls) == 2


def test_search_combines_lexical_and_vector_scores(tmp_path: Path):
    session = _build_session(tmp_path)
    config = _build_config(tmp_path)
    service = WarehouseServiceForTest(config, embedder=FakeEmbedder())

    paper_a = ArxivPaperModel(
        public_id="arxiv_a",
        arxiv_id="2401.00001",
        title="Transformer Paper",
        abstract="semantic ranking",
        authors=["Alice"],
        categories=["cs.LG"],
        created_date=datetime(2024, 1, 1, tzinfo=UTC),
        updated_date=datetime(2024, 1, 2, tzinfo=UTC),
        doi=None,
        source_url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
        search_text="Transformer Paper semantic ranking",
        content_hash="hash-a",
        raw_metadata={},
    )
    paper_b = ArxivPaperModel(
        public_id="arxiv_b",
        arxiv_id="2401.00002",
        title="Keyword Paper",
        abstract="bm25 ranking",
        authors=["Bob"],
        categories=["cs.LG"],
        created_date=datetime(2024, 1, 1, tzinfo=UTC),
        updated_date=datetime(2024, 1, 2, tzinfo=UTC),
        doi=None,
        source_url="https://arxiv.org/abs/2401.00002",
        pdf_url="https://arxiv.org/pdf/2401.00002",
        search_text="Keyword Paper bm25 ranking",
        content_hash="hash-b",
        raw_metadata={},
    )
    session.add_all([paper_a, paper_b])
    session.commit()

    service._run_lexical_query = lambda *args, **kwargs: [
        {"id": paper_a.id, "lexical_score": 0.2},
        {"id": paper_b.id, "lexical_score": 0.9},
    ]
    service._run_vector_query = lambda *args, **kwargs: [
        {"id": paper_a.id, "vector_score": 0.95},
        {"id": paper_b.id, "vector_score": 0.1},
    ]

    hits = service.search(session, query_text="ranking", limit=2, categories=["cs.LG"])
    assert hits[0].paper.arxiv_id == "2401.00001"
    assert hits[0].hybrid_score > hits[1].hybrid_score
    assert hits[0].vector_score == 0.95
    assert hits[1].lexical_score == 0.9


def test_sync_incremental_uses_last_cursor(tmp_path: Path, monkeypatch):
    session = _build_session(tmp_path)
    config = _build_config(tmp_path)
    service = WarehouseServiceForTest(config, embedder=FakeEmbedder())

    previous = ArxivSyncRunModel(
        public_id="sync_prev",
        mode="full",
        source="kaggle",
        status="completed",
        cursor_updated_until=datetime(2024, 1, 5, tzinfo=UTC),
    )
    session.add(previous)
    session.commit()

    monkeypatch.setattr(
        "libs.retrieval.arxiv_warehouse.ArxivMetadataAdapter.search",
        lambda self, query: [],
    )
    monkeypatch.setattr(
        service,
        "_upsert_records",
        lambda db, rows: {
            "inserted": 0,
            "updated": 0,
            "reembedded": 0,
            "skipped": 0,
            "effective_from": previous.cursor_updated_until,
            "effective_until": datetime(2024, 1, 7, tzinfo=UTC),
        },
    )

    run = service.sync_incremental(session, requested_until=datetime(2024, 1, 7, tzinfo=UTC))
    assert run.requested_from == previous.cursor_updated_until
    assert run.cursor_updated_until.date().isoformat() == "2024-01-07"
