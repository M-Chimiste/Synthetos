"""Tests for the MetadataAnalysisPacket schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from libs.discovery.metadata_analysis import MetadataAnalysisPacket


def test_packet_accepts_well_formed_payload() -> None:
    packet = MetadataAnalysisPacket(
        likely_method_family="transformer",
        likely_contribution_type="method",
        shortlist_fit=0.85,
        relevance_to_problem=0.9,
        one_line_summary="Proposes a new attention variant for long sequences.",
        escalation_rationale="Method paper directly addresses the user's problem.",
        risks_or_caveats=["Limited eval"],
    )
    assert packet.shortlist_fit == 0.85
    assert packet.likely_contribution_type == "method"


def test_packet_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        MetadataAnalysisPacket(
            likely_method_family="x",
            likely_contribution_type="method",
            shortlist_fit=1.5,
            relevance_to_problem=0.5,
            one_line_summary="x",
            escalation_rationale="x",
        )


def test_packet_rejects_unknown_contribution_type() -> None:
    with pytest.raises(ValidationError):
        MetadataAnalysisPacket(
            likely_method_family="x",
            likely_contribution_type="not-a-valid-type",  # type: ignore[arg-type]
            shortlist_fit=0.5,
            relevance_to_problem=0.5,
            one_line_summary="x",
            escalation_rationale="x",
        )
