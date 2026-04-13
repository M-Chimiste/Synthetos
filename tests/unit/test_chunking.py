"""Tests for structure-aware chunking from normalized documents."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

from uuid_utils import uuid7

from libs.analysis.chunking import chunk_document
from libs.storage.models.analysis import IngestedDocument


def _make_doc(
    *,
    sections: list[dict] | None = None,
    figures: list[dict] | None = None,
    tables: list[dict] | None = None,
    equations: list[dict] | None = None,
) -> IngestedDocument:
    """Create a minimal IngestedDocument for testing."""
    return IngestedDocument(
        id=UUID(str(uuid7())),
        analysis_session_id=UUID(str(uuid7())),
        paper_card_id=UUID(str(uuid7())),
        fetch_method="html",
        source_url="https://example.com/paper",
        raw_content="<html>...</html>",
        normalized_sections=sections,
        normalized_figures=figures,
        normalized_tables=tables,
        normalized_equations=equations,
        quality_assessment={},
        content_hash="abc123",
    )


def test_chunk_sections():
    """Sections with content produce section chunks."""
    doc = _make_doc(sections=[
        {"heading": "Introduction", "level": 1, "content": "This paper introduces..."},
        {"heading": "Methods", "level": 2, "content": "We use a transformer model."},
    ])
    db = MagicMock()
    session_id = UUID(str(uuid7()))
    paper_id = doc.paper_card_id

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=paper_id,
    )

    assert len(chunks) == 2
    assert chunks[0].chunk_type == "section"
    assert chunks[0].section_path == "Introduction"
    assert chunks[1].section_path == "Methods"
    assert chunks[0].ordinal < chunks[1].ordinal


def test_chunk_paragraphs_from_multiline_section():
    """Long sections with multiple paragraphs produce paragraph chunks."""
    doc = _make_doc(sections=[
        {
            "heading": "Discussion",
            "level": 2,
            "content": "First paragraph.\nSecond paragraph.\nThird paragraph.",
        },
    ])
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    assert len(chunks) == 3
    assert all(c.chunk_type == "paragraph" for c in chunks)
    assert all(c.section_path == "Discussion" for c in chunks)


def test_chunk_figures():
    """Figures produce figure chunks."""
    doc = _make_doc(
        sections=[{"heading": "Intro", "level": 1, "content": "Text"}],
        figures=[
            {"id": "fig-1", "caption": "Architecture diagram", "page": 3},
        ],
    )
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    figure_chunks = [c for c in chunks if c.chunk_type == "figure"]
    assert len(figure_chunks) == 1
    assert "fig-1" in figure_chunks[0].content


def test_chunk_tables():
    """Tables produce table chunks."""
    doc = _make_doc(
        sections=[{"heading": "Intro", "level": 1, "content": "Text"}],
        tables=[
            {"id": "table-1", "caption": "Results comparison", "page": 5},
        ],
    )
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1
    assert "table-1" in table_chunks[0].content


def test_chunk_equations():
    """Equations produce equation chunks."""
    doc = _make_doc(
        sections=[{"heading": "Intro", "level": 1, "content": "Text"}],
        equations=[
            {"id": "eq-1", "latex": "E=mc^2", "context": "energy equivalence"},
        ],
    )
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    eq_chunks = [c for c in chunks if c.chunk_type == "equation"]
    assert len(eq_chunks) == 1
    assert "E=mc^2" in eq_chunks[0].content


def test_chunk_max_limit():
    """Chunking respects the max_chunks limit."""
    sections = [
        {"heading": f"Section {i}", "level": 2, "content": f"Content {i}"}
        for i in range(100)
    ]
    doc = _make_doc(sections=sections)
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
        max_chunks=10,
    )

    assert len(chunks) <= 10


def test_chunk_empty_sections_skipped():
    """Sections with no content are skipped."""
    doc = _make_doc(sections=[
        {"heading": "Empty", "level": 1, "content": ""},
        {"heading": "Has Content", "level": 1, "content": "Real content here."},
    ])
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    assert len(chunks) == 1
    assert chunks[0].section_path == "Has Content"


def test_chunk_content_hash_unique():
    """Each chunk gets a unique content hash."""
    doc = _make_doc(sections=[
        {"heading": "A", "level": 1, "content": "Content A"},
        {"heading": "B", "level": 1, "content": "Content B"},
    ])
    db = MagicMock()
    session_id = UUID(str(uuid7()))

    chunks = chunk_document(
        db,
        doc=doc,
        analysis_session_id=session_id,
        paper_card_id=doc.paper_card_id,
    )

    hashes = {c.content_hash for c in chunks}
    assert len(hashes) == len(chunks)
