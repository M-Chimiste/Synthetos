"""Unit tests for libs.ideation.protocol_compiler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from libs.ideation.protocol_compiler import (
    ParameterVariationRequest,
    ProtocolCompileRequest,
    _parse_protocol_json,
    _parse_variation_json,
    compile_parameter_variation,
    compile_protocol,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_compile_protocol_produces_valid_spec():
    with open(FIXTURES_DIR / "sample_protocol_response.json") as f:
        text = f.read()
    result = _parse_protocol_json(text)
    assert result.title == "Adaptive Weight Sharing NAS Experiment"
    assert len(result.metrics) == 3
    assert len(result.datasets) == 1
    assert result.gpu_required is True
    assert result.estimated_runtime_minutes == 480
    assert result.baseline_description.startswith("Uniform weight sharing")


def test_compile_protocol_fallback():
    gateway = MagicMock()
    gateway.call_chat_completion.side_effect = RuntimeError("LLM down")

    request = ProtocolCompileRequest(
        hypothesis={"title": "H", "statement": "S", "approach_summary": "A"},
        evidence=[],
        charter_problem="Test",
        charter_criteria={},
        constraints={},
    )
    result = compile_protocol(gateway, request)
    # Should get default empty response
    assert result.title == "Untitled Experiment"
    assert result.metrics == []


def test_compile_protocol_with_mock():
    with open(FIXTURES_DIR / "sample_protocol_response.json") as f:
        fixture_text = f.read()

    gateway = MagicMock()
    gateway.call_chat_completion.return_value = fixture_text

    request = ProtocolCompileRequest(
        hypothesis={"title": "NAS", "statement": "S", "approach_summary": "A"},
        evidence=[{"claim": "Test", "evidence_type": "finding", "strength": "strong"}],
        charter_problem="Efficient NAS",
        charter_criteria={"key": "value"},
        constraints={},
    )
    result = compile_protocol(gateway, request)
    assert result.title == "Adaptive Weight Sharing NAS Experiment"
    assert len(result.controls) == 2
    assert len(result.stop_conditions) == 2
    gateway.call_chat_completion.assert_called_once()


def test_parse_protocol_json_malformed():
    result = _parse_protocol_json("Not valid JSON")
    assert result.title == "Untitled Experiment"
    assert result.metrics == []


def test_parse_parameter_variation_json():
    result = _parse_variation_json(
        """
        {
          "varied_controls": [
            {"name": "learning_rate", "value": 0.001, "rationale": "reduce oscillation"}
          ],
          "method_modification": "Use a smaller learning rate with warmup.",
          "expected_impact": "Stabilize validation accuracy."
        }
        """
    )
    assert result.varied_controls[0]["name"] == "learning_rate"
    assert "smaller learning rate" in result.method_modification.lower()


def test_compile_parameter_variation_with_mock():
    gateway = MagicMock()
    gateway.call_chat_completion.return_value = """
    {
      "varied_controls": [
        {"name": "batch_size", "value": 64, "rationale": "more stable gradients"}
      ],
      "method_modification": "Increase batch size and shorten warmup.",
      "expected_impact": "Reduce noise."
    }
    """

    request = ParameterVariationRequest(
        hypothesis_title="NAS",
        objective="Improve validation accuracy",
        method_description="Train a baseline model.",
        current_controls=[{"name": "batch_size", "value": 32}],
        recent_runs=[{"public_id": "run-1", "metrics": {"accuracy": 0.8}, "signal": "stalled"}],
        directional_signal="stalled",
        hypothesis_run_count=3,
        variation_hints=[{"reason": "stall_break"}],
    )
    result = compile_parameter_variation(gateway, request)

    assert result.varied_controls[0]["value"] == 64
    assert "noise" in result.expected_impact.lower()
    gateway.call_chat_completion.assert_called_once()
