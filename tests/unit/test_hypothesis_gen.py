"""Unit tests for libs.ideation.hypothesis_gen."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from libs.ideation.hypothesis_gen import (
    HypothesisGenRequest,
    _parse_hypotheses_json,
    generate_hypotheses,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_generate_hypotheses_parses_response():
    with open(FIXTURES_DIR / "sample_hypotheses_response.json") as f:
        text = f.read()
    items = _parse_hypotheses_json(text)
    assert len(items) == 3
    assert items[0].title == "Adaptive Weight Sharing for Efficient NAS"
    assert len(items[0].supporting_evidence_ids) == 2


def test_generate_hypotheses_handles_failure():
    gateway = MagicMock()
    gateway.call_chat_completion.side_effect = RuntimeError("LLM unavailable")

    request = HypothesisGenRequest(
        charter_problem="Test problem",
        charter_criteria={},
        evidence_summary=[],
        num_hypotheses=3,
    )
    response = generate_hypotheses(gateway, request)
    assert len(response.hypotheses) == 0


def test_generate_hypotheses_with_mock_gateway():
    with open(FIXTURES_DIR / "sample_hypotheses_response.json") as f:
        fixture_text = f.read()

    gateway = MagicMock()
    gateway.call_chat_completion.return_value = fixture_text

    request = HypothesisGenRequest(
        charter_problem="Efficient NAS",
        charter_criteria={"key": "value"},
        evidence_summary=[
            {"public_id": "evidence_001", "claim": "Test", "evidence_type": "finding",
             "strength": "strong", "relevance_score": 0.9},
        ],
        num_hypotheses=3,
    )
    response = generate_hypotheses(gateway, request)
    assert len(response.hypotheses) == 3
    gateway.call_chat_completion.assert_called_once()
