"""Unit tests for libs.ideation.extraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from libs.ideation.extraction import (
    EvidenceExtractionRequest,
    _parse_evidence_json,
    extract_evidence_batch,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_parse_evidence_json_valid():
    with open(FIXTURES_DIR / "sample_evidence_response.json") as f:
        text = f.read()
    items = _parse_evidence_json(text, "paper_001")
    assert len(items) == 3
    assert items[0].claim.startswith("Neural architecture search")
    assert items[0].evidence_type == "finding"
    assert items[0].strength == "strong"
    assert items[0].relevance_score == 0.92


def test_parse_evidence_json_with_surrounding_text():
    text = (
        "Here are the extracted claims:\n"
        '[{"claim": "Test claim", "evidence_type": "method", '
        '"strength": "moderate", "relevance_score": 0.7, '
        '"relevance_rationale": "Relevant"}]'
        "\nEnd of response."
    )
    items = _parse_evidence_json(text, "paper_002")
    assert len(items) == 1
    assert items[0].claim == "Test claim"


def test_parse_evidence_json_malformed():
    text = "This is not valid JSON at all."
    items = _parse_evidence_json(text, "paper_003")
    assert len(items) == 0


def test_extract_evidence_batch_mocked():
    gateway = MagicMock()
    gateway.call_chat_completion.return_value = json.dumps([
        {
            "claim": "Test claim",
            "evidence_type": "finding",
            "strength": "strong",
            "relevance_score": 0.9,
            "relevance_rationale": "Important",
            "source_section": "abstract",
            "source_quote": None,
        }
    ])

    requests = [
        EvidenceExtractionRequest(
            paper_id="paper_001",
            title="Test Paper",
            abstract="Test abstract",
            charter_problem="Test problem",
            charter_criteria={},
        ),
    ]

    results = extract_evidence_batch(gateway, requests)
    assert len(results) == 1
    assert results[0].paper_id == "paper_001"
    assert len(results[0].evidence_items) == 1
    assert results[0].evidence_items[0].claim == "Test claim"
    gateway.call_chat_completion.assert_called_once()
