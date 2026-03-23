"""Tests for report structural quality scoring."""

from __future__ import annotations

from libs.reporting.scoring import REQUIRED_SECTIONS, score_report_structure


class TestScoreReportStructure:
    def test_empty_report_low_score(self) -> None:
        result = score_report_structure("", "cycle_summary")
        assert result["structural_score"] == 0.0
        assert result["word_count"] == 0
        assert not any(result["section_checklist"].values())

    def test_complete_cycle_summary(self) -> None:
        md = """
# Cycle Summary

## Problem & Approach
This is the problem statement and approach section with enough words to pass.

## Literature Summary
Papers screened and results found in the literature review phase.

## Hypothesis Portfolio
Ranked hypotheses based on evidence strength and novelty.

## Experiment Results
Run results showing metrics improvements over baseline 0.85.

## Verification Outcomes
All runs verified with robust outcomes.

## Recommendations
Next steps include further experiments and literature review.

| Metric | Value |
|--------|-------|
| accuracy | 0.92 |
"""
        result = score_report_structure(md, "cycle_summary")
        assert result["structural_score"] > 0.7
        assert result["word_count"] > 50
        assert result["has_tables"] is True
        assert result["has_metrics"] is True
        # All required sections should be found
        for section, found in result["section_checklist"].items():
            assert found, f"Section '{section}' should be found"

    def test_partial_cycle_summary(self) -> None:
        md = """
# Cycle Summary

## Problem & Approach
Brief problem description.

## Recommendations
Do more experiments.
"""
        result = score_report_structure(md, "cycle_summary")
        assert 0.0 < result["structural_score"] < 1.0
        checklist = result["section_checklist"]
        assert checklist.get("Problem") is True
        assert checklist.get("Recommendation") is True
        assert checklist.get("Literature") is False

    def test_run_summary_report_type(self) -> None:
        md = """
# Run Summary

## Experiment Setup
Setup details here.

## Execution Summary
Ran successfully.

## Results
Accuracy: 0.91

## Artifacts
- metrics.json
- predictions.csv

## Assessment
Good run overall.
"""
        result = score_report_structure(md, "run_summary")
        assert result["structural_score"] > 0.6
        assert all(result["section_checklist"].values())

    def test_evidence_summary_type(self) -> None:
        md = """
## Evidence Overview
Summary of evidence.

## Synthesis
Key themes identified.

## Gaps
Missing data on topic X.

## Implications for Hypotheses
Evidence supports hypothesis A.
"""
        result = score_report_structure(md, "evidence_summary")
        assert all(result["section_checklist"].values())

    def test_unknown_report_type_uses_empty_sections(self) -> None:
        result = score_report_structure("Some text here with enough words.", "unknown_type")
        assert result["section_checklist"] == {}
        assert result["word_count"] > 0
        assert result["structural_score"] > 0.0

    def test_table_detection(self) -> None:
        md = """
| Col1 | Col2 |
|------|------|
| a    | b    |
"""
        result = score_report_structure(md, "cycle_summary")
        assert result["has_tables"] is True

    def test_metric_detection(self) -> None:
        md = "The accuracy was 0.95 on the validation set."
        result = score_report_structure(md, "cycle_summary")
        assert result["has_metrics"] is True

    def test_no_metrics_detected(self) -> None:
        md = "No numerical results yet."
        result = score_report_structure(md, "cycle_summary")
        assert result["has_metrics"] is False

    def test_word_count_meets_minimum(self) -> None:
        md = " ".join(["word"] * 250)
        result = score_report_structure(md, "cycle_summary")
        assert result["word_count"] == 250
        # Word score should be 1.0 since 250 > 200 minimum
        assert result["structural_score"] > 0.3

    def test_all_known_report_types_have_sections(self) -> None:
        for report_type in REQUIRED_SECTIONS:
            sections = REQUIRED_SECTIONS[report_type]
            assert len(sections) >= 2, f"{report_type} should have at least 2 required sections"
