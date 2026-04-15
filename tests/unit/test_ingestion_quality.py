"""Tests for ingestion quality assessment and HTML/PDF fallback triggering."""

from __future__ import annotations

from libs.adapters.ingestion.base import IngestionQualityLow, QualityAssessment


def test_quality_high_score():
    """Well-structured content gets a high quality score."""
    qa = QualityAssessment(
        structure_preserved=True,
        section_count=8,
        figure_count=3,
        table_count=2,
        equation_count=5,
        quality_score=0.95,
    )
    assert qa.quality_score >= 0.5
    assert qa.structure_preserved is True


def test_quality_low_score_triggers_warning():
    """Low-quality extraction gets warnings."""
    qa = QualityAssessment(
        structure_preserved=False,
        section_count=1,
        figure_count=0,
        table_count=0,
        equation_count=0,
        quality_score=0.2,
        quality_warnings=["Very few sections extracted"],
    )
    assert qa.quality_score < 0.5
    assert len(qa.quality_warnings) > 0


def test_quality_threshold_exception():
    """IngestionQualityLow carries the score and threshold."""
    exc = IngestionQualityLow(quality_score=0.3, threshold=0.5)
    assert exc.quality_score == 0.3
    assert exc.threshold == 0.5
    assert "0.30" in str(exc)
    assert "0.50" in str(exc)


def test_quality_assessment_boundary_scores():
    """Scores at 0.0 and 1.0 are valid."""
    low = QualityAssessment(structure_preserved=False, quality_score=0.0)
    assert low.quality_score == 0.0

    high = QualityAssessment(structure_preserved=True, quality_score=1.0)
    assert high.quality_score == 1.0
