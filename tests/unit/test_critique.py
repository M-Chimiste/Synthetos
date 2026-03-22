"""Unit tests for libs.ideation.critique."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from libs.ideation.critique import (
    CritiqueRequest,
    _parse_critique_json,
    critique_hypothesis,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_critique_parses_scores():
    with open(FIXTURES_DIR / "sample_critique_response.json") as f:
        text = f.read()
    result = _parse_critique_json(text)
    assert result.novelty_score == 0.75
    assert result.feasibility_score == 0.85
    assert result.impact_score == 0.70
    assert "reasonable extension" in result.critique_summary


def test_critique_identifies_blocking_issues():
    text = json.dumps({
        "novelty_score": 0.3,
        "feasibility_score": 0.2,
        "impact_score": 0.4,
        "critique_summary": "Hypothesis has critical flaws",
        "issues": [
            {"issue": "No viable dataset", "severity": "blocking"},
            {"issue": "Minor wording", "severity": "note"},
        ],
    })
    result = _parse_critique_json(text)
    assert result.feasibility_score == 0.2
    blocking = [i for i in result.issues if i.get("severity") == "blocking"]
    assert len(blocking) == 1


def test_critique_handles_malformed():
    result = _parse_critique_json("Not valid JSON at all")
    assert result.novelty_score == 0.5  # defaults
    assert "Failed to parse" in result.critique_summary


def test_critique_hypothesis_with_mock():
    with open(FIXTURES_DIR / "sample_critique_response.json") as f:
        fixture_text = f.read()

    gateway = MagicMock()
    gateway.call_chat_completion.return_value = fixture_text

    request = CritiqueRequest(
        hypothesis_title="Test Hypothesis",
        statement="We hypothesize...",
        rationale="Because...",
        approach_summary="Train and compare",
        supporting_evidence=[{"claim": "Evidence A"}],
        counter_evidence=[],
        charter_problem="Test problem",
    )
    response = critique_hypothesis(gateway, request)
    assert response.novelty_score == 0.75
    assert response.feasibility_score == 0.85
    gateway.call_chat_completion.assert_called_once()
