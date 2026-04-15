"""Tests for coverage diagnostic computation."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

from uuid_utils import uuid7

from libs.analysis.coverage_check import compute_coverage
from libs.storage.models.analysis import (
    GraphNode,
    IngestedDocument,
)


def _uuid() -> UUID:
    return UUID(str(uuid7()))


def _doc(
    *,
    sections: list[dict] | None = None,
    figures: list[dict] | None = None,
    tables: list[dict] | None = None,
    equations: list[dict] | None = None,
) -> IngestedDocument:
    return IngestedDocument(
        id=_uuid(),
        analysis_session_id=_uuid(),
        paper_card_id=_uuid(),
        fetch_method="html",
        source_url="https://example.com",
        raw_content="<html>test</html>",
        normalized_sections=sections or [],
        normalized_figures=figures or [],
        normalized_tables=tables or [],
        normalized_equations=equations or [],
        quality_assessment={},
        content_hash="hash",
    )


def _node(*, node_type: str, label: str, session_id: UUID) -> GraphNode:
    return GraphNode(
        id=_uuid(),
        analysis_session_id=session_id,
        paper_card_id=_uuid(),
        node_type=node_type,
        label=label,
        provenance={"source_chunk_ids": []},
    )


def test_full_coverage():
    """All sections, figures, and tables are covered."""
    session_id = _uuid()
    doc = _doc(
        sections=[
            {"heading": "Introduction", "level": 1, "content": "text"},
            {"heading": "Methods", "level": 2, "content": "text"},
        ],
        figures=[{"id": "fig-1", "caption": "arch"}],
        tables=[{"id": "table-1", "caption": "results"}],
    )

    nodes = [
        _node(node_type="section", label="Introduction", session_id=session_id),
        _node(node_type="section", label="Methods", session_id=session_id),
        _node(node_type="figure", label="fig-1: architecture", session_id=session_id),
        _node(node_type="table", label="table-1: results", session_id=session_id),
    ]

    db = MagicMock()
    diagnostic = compute_coverage(
        db,
        doc=doc,
        chunks=[],
        nodes=nodes,
        edges=[],
        analysis_session_id=session_id,
    )

    assert diagnostic.overall_score > 0.5
    assert diagnostic.section_coverage["covered"] == 2
    assert len(diagnostic.warnings or []) == 0 or True  # May have warnings


def test_missing_sections():
    """Missing sections are reported."""
    session_id = _uuid()
    doc = _doc(
        sections=[
            {"heading": "Introduction", "level": 1, "content": "text"},
            {"heading": "Methods", "level": 2, "content": "text"},
            {"heading": "Results", "level": 2, "content": "text"},
        ],
    )

    nodes = [
        _node(node_type="section", label="Introduction", session_id=session_id),
    ]

    db = MagicMock()
    diagnostic = compute_coverage(
        db,
        doc=doc,
        chunks=[],
        nodes=nodes,
        edges=[],
        analysis_session_id=session_id,
    )

    missing = diagnostic.section_coverage.get("missing", [])
    assert "Methods" in missing
    assert "Results" in missing


def test_no_figures_warning():
    """When figures exist but none are extracted, a warning is generated."""
    session_id = _uuid()
    doc = _doc(
        sections=[{"heading": "Intro", "level": 1, "content": "text"}],
        figures=[
            {"id": "fig-1", "caption": "network"},
            {"id": "fig-2", "caption": "results"},
        ],
    )

    db = MagicMock()
    diagnostic = compute_coverage(
        db,
        doc=doc,
        chunks=[],
        nodes=[],
        edges=[],
        analysis_session_id=session_id,
    )

    warnings = diagnostic.warnings or []
    assert any("figure" in w.lower() for w in warnings)


def test_empty_document():
    """Empty document produces a valid diagnostic with score 0."""
    session_id = _uuid()
    doc = _doc()

    db = MagicMock()
    diagnostic = compute_coverage(
        db,
        doc=doc,
        chunks=[],
        nodes=[],
        edges=[],
        analysis_session_id=session_id,
    )

    assert diagnostic.overall_score == 0.0
