"""Postgres integration tests for arXiv warehouse pgvector + FTS queries.

Requires: testcontainers, Docker, pgvector/pgvector:pg16 image.
These tests are skipped automatically when dependencies are unavailable.
Run with: uv run pytest tests/integration/test_arxiv_warehouse_pg.py -v -m integration
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from libs.core.config import AppConfig

try:
    from testcontainers.postgres import PostgresContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_TESTCONTAINERS, reason="testcontainers not installed"),
]


@pytest.fixture(scope="module")
def pg_session():
    """Start a pgvector Postgres container and yield a session."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from libs.storage.base import Base

    container = PostgresContainer("pgvector/pgvector:pg16")
    try:
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker unavailable or image not pulled: {exc}")

    url = container.get_connection_url()
    engine = create_engine(url)

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        container.stop()


def _insert_paper(
    session,
    *,
    arxiv_id: str,
    title: str,
    abstract: str,
    categories: list[str],
    created_date: datetime | None = None,
    embedding: list[float] | None = None,
):
    """Insert a paper directly via SQL for test isolation."""
    from sqlalchemy import text

    from libs.core.ids import generate_public_id

    search_text = f"{title} {abstract}"
    session.execute(
        text(
            """
            INSERT INTO arxiv_papers (
                public_id, arxiv_id, title, abstract, authors, categories,
                created_date, source_url, pdf_url, search_text, content_hash,
                raw_metadata, embedding, embedding_model_id, created_at, updated_at
            ) VALUES (
                :public_id, :arxiv_id, :title, :abstract, :authors, :categories,
                :created_date, :source_url, :pdf_url, :search_text, :content_hash,
                :raw_metadata, CAST(:embedding AS vector), :embedding_model_id,
                NOW(), NOW()
            )
            """
        ),
        {
            "public_id": generate_public_id("axp"),
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": json.dumps(["Test Author"]),
            "categories": json.dumps(categories),
            "created_date": created_date,
            "source_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "search_text": search_text,
            "content_hash": f"hash_{arxiv_id}",
            "raw_metadata": json.dumps({}),
            "embedding": _vector_literal(embedding) if embedding else None,
            "embedding_model_id": "test-model" if embedding else None,
        },
    )
    session.commit()


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vec) + "]"


# --- Tests ---


def test_lexical_fts_query(pg_session):
    """Full-text search returns papers matching query terms with scores."""
    _insert_paper(
        pg_session,
        arxiv_id="fts.001",
        title="Neural Architecture Search for Efficient Models",
        abstract="We propose a method for neural architecture search.",
        categories=["cs.LG"],
        created_date=datetime(2024, 1, 15, tzinfo=UTC),
    )
    _insert_paper(
        pg_session,
        arxiv_id="fts.002",
        title="Quantum Computing Basics",
        abstract="An introduction to quantum computing fundamentals.",
        categories=["quant-ph"],
        created_date=datetime(2024, 1, 20, tzinfo=UTC),
    )

    db_url = str(pg_session.bind.url)
    config = AppConfig(
        env="test",
        db_url=db_url,
        data_root="/tmp/test_data",
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = []

    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    warehouse = ArxivWarehouseService(config, embedder=mock_embedder)

    rows = warehouse._run_lexical_query(
        pg_session,
        query_text="neural architecture search",
        categories=[],
        date_from=None,
        date_until=None,
        limit=10,
    )

    assert len(rows) >= 1
    ids = {row["id"] for row in rows}
    # fts.001 should match, fts.002 should not
    paper_001 = pg_session.execute(
        __import__("sqlalchemy").text("SELECT id FROM arxiv_papers WHERE arxiv_id = 'fts.001'")
    ).scalar()
    assert paper_001 in ids
    assert all(row["lexical_score"] > 0 for row in rows)


def test_vector_cosine_query(pg_session):
    """Vector similarity search returns papers ordered by cosine similarity."""
    dim = 768
    # Paper A: embedding close to query
    emb_a = [1.0] + [0.0] * (dim - 1)
    # Paper B: embedding far from query
    emb_b = [0.0] * (dim - 1) + [1.0]

    _insert_paper(
        pg_session,
        arxiv_id="vec.001",
        title="Vector Close Paper",
        abstract="This paper is semantically close to the query.",
        categories=["cs.IR"],
        embedding=emb_a,
    )
    _insert_paper(
        pg_session,
        arxiv_id="vec.002",
        title="Vector Far Paper",
        abstract="This paper is semantically far from the query.",
        categories=["cs.IR"],
        embedding=emb_b,
    )

    db_url = str(pg_session.bind.url)
    config = AppConfig(
        env="test",
        db_url=db_url,
        data_root="/tmp/test_data",
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    mock_embedder = MagicMock()

    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    warehouse = ArxivWarehouseService(config, embedder=mock_embedder)

    # Query vector similar to emb_a
    query_vector = [0.9] + [0.1] * (dim - 1)
    rows = warehouse._run_vector_query(
        pg_session,
        vector=query_vector,
        categories=[],
        date_from=None,
        date_until=None,
        limit=10,
    )

    assert len(rows) >= 2
    # First result should be closer to the query vector
    assert rows[0]["vector_score"] > rows[1]["vector_score"]


def test_category_filter_jsonb(pg_session):
    """Category filter correctly uses jsonb overlap matching."""
    _insert_paper(
        pg_session,
        arxiv_id="cat.001",
        title="Machine Learning Paper About Categories",
        abstract="A paper about machine learning categorization methods.",
        categories=["cs.LG", "cs.AI"],
    )
    _insert_paper(
        pg_session,
        arxiv_id="cat.002",
        title="Biology Paper About Categories",
        abstract="A paper about biological categorization systems.",
        categories=["q-bio.GN"],
    )

    db_url = str(pg_session.bind.url)
    config = AppConfig(
        env="test",
        db_url=db_url,
        data_root="/tmp/test_data",
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    mock_embedder = MagicMock()

    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    warehouse = ArxivWarehouseService(config, embedder=mock_embedder)

    # Search with cs.LG category filter
    rows = warehouse._run_lexical_query(
        pg_session,
        query_text="categorization",
        categories=["cs.LG"],
        date_from=None,
        date_until=None,
        limit=10,
    )

    arxiv_ids = set()
    for row in rows:
        paper = pg_session.execute(
            __import__("sqlalchemy").text(
                "SELECT arxiv_id FROM arxiv_papers WHERE id = :id"
            ),
            {"id": row["id"]},
        ).scalar()
        arxiv_ids.add(paper)

    assert "cat.001" in arxiv_ids
    assert "cat.002" not in arxiv_ids


def test_date_range_filter(pg_session):
    """Date range filters correctly bound results."""
    _insert_paper(
        pg_session,
        arxiv_id="date.001",
        title="Early Paper About Date Filtering",
        abstract="A paper from early January about date filtering.",
        categories=["cs.DB"],
        created_date=datetime(2024, 1, 5, tzinfo=UTC),
    )
    _insert_paper(
        pg_session,
        arxiv_id="date.002",
        title="Late Paper About Date Filtering",
        abstract="A paper from late March about date filtering.",
        categories=["cs.DB"],
        created_date=datetime(2024, 3, 25, tzinfo=UTC),
    )

    db_url = str(pg_session.bind.url)
    config = AppConfig(
        env="test",
        db_url=db_url,
        data_root="/tmp/test_data",
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    mock_embedder = MagicMock()

    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    warehouse = ArxivWarehouseService(config, embedder=mock_embedder)

    # Search with date range that only includes the early paper
    rows = warehouse._run_lexical_query(
        pg_session,
        query_text="date filtering",
        categories=[],
        date_from=datetime(2024, 1, 1, tzinfo=UTC),
        date_until=datetime(2024, 1, 31, tzinfo=UTC),
        limit=10,
    )

    paper_ids = set()
    for row in rows:
        paper = pg_session.execute(
            __import__("sqlalchemy").text(
                "SELECT arxiv_id FROM arxiv_papers WHERE id = :id"
            ),
            {"id": row["id"]},
        ).scalar()
        paper_ids.add(paper)

    assert "date.001" in paper_ids
    assert "date.002" not in paper_ids


def test_hybrid_search_end_to_end(pg_session):
    """End-to-end hybrid search combines lexical and vector scores."""
    dim = 768
    _insert_paper(
        pg_session,
        arxiv_id="hyb.001",
        title="Hybrid Search Paper About Neural Networks",
        abstract="Combining lexical and semantic search for neural networks.",
        categories=["cs.IR"],
        embedding=[1.0] + [0.0] * (dim - 1),
    )

    db_url = str(pg_session.bind.url)
    config = AppConfig(
        env="test",
        db_url=db_url,
        data_root="/tmp/test_data",
        model_config_path="configs/models/routes.yaml",
        policy_config_path="configs/policies/default.yaml",
        skill_paths=["skills"],
        auto_init_db=False,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.9] + [0.1] * (dim - 1)

    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    warehouse = ArxivWarehouseService(config, embedder=mock_embedder)

    hits = warehouse.search(
        pg_session,
        query_text="neural networks search",
        limit=10,
    )

    assert len(hits) >= 1
    hit = hits[0]
    assert hit.hybrid_score > 0
    assert hit.paper.arxiv_id == "hyb.001"
