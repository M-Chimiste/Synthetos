"""Unit tests for libs.literature.triage."""

from __future__ import annotations

from libs.literature.triage import _parse_triage_json


def test_parse_triage_json_valid():
    text = '{"decision": "advance", "score": 0.85, "rationale": "Highly relevant paper."}'
    result = _parse_triage_json(text, "paper_001")
    assert result.decision == "advance"
    assert result.score == 0.85
    assert "relevant" in result.rationale


def test_parse_triage_json_with_surrounding_text():
    text = (
        'Here is my evaluation:\n'
        '{"decision": "reject", "score": 0.2, "rationale": "Not relevant."}'
        '\nEnd.'
    )
    result = _parse_triage_json(text, "paper_002")
    assert result.decision == "reject"
    assert result.score == 0.2


def test_parse_triage_json_malformed():
    text = "This is not valid JSON at all."
    result = _parse_triage_json(text, "paper_003")
    assert result.decision == "uncertain"
    assert result.score == 0.5
    assert "Failed to parse" in result.rationale


def test_parse_triage_json_missing_fields():
    text = '{"decision": "advance"}'
    result = _parse_triage_json(text, "paper_004")
    assert result.decision == "advance"
    assert result.score == 0.5  # default
