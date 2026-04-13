"""Tests for Phase 2 analysis Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from libs.schemas.analysis import (
    AnalysisBudget,
    AnalysisSessionStartRequest,
    ChunkRef,
    ContradictionFlag,
    CoverageDetail,
    EvidenceCardCreate,
    LocateRequest,
    NodeRef,
    NormalizedEquation,
    NormalizedFigure,
    NormalizedSection,
    NormalizedTable,
    QARequest,
    QualityAssessment,
)


def test_normalized_section_valid():
    s = NormalizedSection(heading="Introduction", level=1, content="Some text")
    assert s.heading == "Introduction"
    assert s.level == 1


def test_normalized_section_level_bounds():
    with pytest.raises(ValidationError):
        NormalizedSection(heading="x", level=-1, content="y")
    with pytest.raises(ValidationError):
        NormalizedSection(heading="x", level=11, content="y")


def test_normalized_figure():
    f = NormalizedFigure(id="fig-1", caption="A figure", page=3)
    assert f.id == "fig-1"
    assert f.page == 3


def test_normalized_table():
    t = NormalizedTable(id="table-1", caption="A table")
    assert t.page is None


def test_normalized_equation():
    e = NormalizedEquation(id="eq-1", latex="E=mc^2", context="relativity")
    assert e.latex == "E=mc^2"


def test_quality_assessment_bounds():
    qa = QualityAssessment(
        structure_preserved=True,
        quality_score=0.8,
        section_count=5,
    )
    assert qa.quality_score == 0.8

    with pytest.raises(ValidationError):
        QualityAssessment(structure_preserved=True, quality_score=1.5)
    with pytest.raises(ValidationError):
        QualityAssessment(structure_preserved=True, quality_score=-0.1)


def test_analysis_budget_defaults():
    b = AnalysisBudget()
    assert b.max_chunks == 500
    assert b.graph_extraction_concurrency == 4
    assert b.html_quality_threshold == 0.5


def test_analysis_session_start_request_default():
    r = AnalysisSessionStartRequest()
    assert r.budget.max_chunks == 500


def test_evidence_card_create_valid():
    e = EvidenceCardCreate(
        paper_card_id="00000000-0000-0000-0000-000000000001",
        evidence_type="finding",
        claim="Transformers outperform RNNs",
        confidence=0.9,
    )
    assert e.evidence_type == "finding"


def test_evidence_card_create_invalid_type():
    with pytest.raises(ValidationError):
        EvidenceCardCreate(
            paper_card_id="00000000-0000-0000-0000-000000000001",
            evidence_type="invalid_type",
            claim="something",
        )


def test_contradiction_flag():
    cf = ContradictionFlag(
        evidence_id="00000000-0000-0000-0000-000000000001",
        reason="opposing results",
        model_confidence=0.85,
    )
    assert cf.model_confidence == 0.85


def test_qa_request_bounds():
    q = QARequest(question="What is the method?")
    assert q.max_chunks == 10
    assert q.expand_graph is True

    with pytest.raises(ValidationError):
        QARequest(question="")  # min_length=1


def test_locate_request_valid():
    r = LocateRequest(entity_type="concept", query="attention")
    assert r.entity_type == "concept"

    with pytest.raises(ValidationError):
        LocateRequest(entity_type="invalid", query="test")


def test_coverage_detail():
    cd = CoverageDetail(total=10, covered=7, missing=["sec-3", "sec-5"])
    assert len(cd.missing) == 2


def test_chunk_ref():
    cr = ChunkRef(
        chunk_id="00000000-0000-0000-0000-000000000001",
        section_path="3.2 Methods",
        ordinal=5,
        snippet="We use a transformer...",
    )
    assert cr.section_path == "3.2 Methods"


def test_node_ref():
    nr = NodeRef(
        node_id="00000000-0000-0000-0000-000000000001",
        node_type="method",
        label="BERT",
    )
    assert nr.node_type == "method"
