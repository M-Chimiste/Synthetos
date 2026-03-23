"""Structural quality scoring for generated reports."""

from __future__ import annotations

import re

# Required sections by report type.
REQUIRED_SECTIONS: dict[str, list[str]] = {
    "cycle_summary": [
        "Problem",
        "Literature",
        "Hypothesis",
        "Experiment",
        "Verification",
        "Recommendation",
    ],
    "run_summary": [
        "Experiment Setup",
        "Execution",
        "Results",
        "Artifacts",
        "Assessment",
    ],
    "evidence_summary": [
        "Evidence Overview",
        "Synthesis",
        "Gaps",
        "Implications",
    ],
    "literature_screening": [
        "Screening",
        "Results",
        "Summary",
    ],
    "verification_report": [
        "Outcome",
        "Checks",
        "Summary",
    ],
    "failure_postmortem": [
        "Root Cause",
        "Remediation",
    ],
}

# Minimum word count thresholds by report type.
MIN_WORD_COUNTS: dict[str, int] = {
    "cycle_summary": 200,
    "run_summary": 100,
    "evidence_summary": 150,
    "literature_screening": 100,
    "verification_report": 80,
    "failure_postmortem": 80,
}


def score_report_structure(markdown: str, report_type: str) -> dict:
    """Score the structural quality of a markdown report.

    Returns a dict with:
    - structural_score: float 0.0-1.0
    - word_count: int
    - section_checklist: dict of section_name -> bool
    - has_tables: bool
    - has_metrics: bool
    """
    required = REQUIRED_SECTIONS.get(report_type, [])
    heading_pattern = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
    headings = [m.group(1).strip().lower() for m in heading_pattern.finditer(markdown)]

    section_checklist: dict[str, bool] = {}
    for section in required:
        section_lower = section.lower()
        section_checklist[section] = any(section_lower in h for h in headings)

    sections_found = sum(section_checklist.values())
    sections_total = max(len(required), 1)
    section_score = sections_found / sections_total

    word_count = len(markdown.split())
    min_words = MIN_WORD_COUNTS.get(report_type, 80)
    word_score = min(word_count / min_words, 1.0) if min_words > 0 else 1.0

    has_tables = "|" in markdown and "---" in markdown
    has_metrics = bool(re.search(r"\d+\.\d+", markdown))

    bonus = 0.0
    if has_tables:
        bonus += 0.05
    if has_metrics:
        bonus += 0.05

    structural_score = min((section_score * 0.6 + word_score * 0.4) + bonus, 1.0)

    return {
        "structural_score": round(structural_score, 3),
        "word_count": word_count,
        "section_checklist": section_checklist,
        "has_tables": has_tables,
        "has_metrics": has_metrics,
    }
