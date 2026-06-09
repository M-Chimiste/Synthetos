"""Tests for experiment metric parsing."""

from __future__ import annotations

import json

from libs.execution.metrics import parse_metrics


def test_parse_metrics_ignores_nonnumeric_extra_fields(tmp_path) -> None:
    artifacts = tmp_path
    (artifacts / "metrics.json").write_text(
        json.dumps(
            {
                "loss": 1.25,
                "training_time_s": 2,
                "best_model": "Standard",
            }
        ),
        encoding="utf-8",
    )

    parsed = parse_metrics(
        artifacts,
        [
            {"name": "loss"},
            {"name": "training_time_s"},
        ],
    )

    assert parsed.ok is True
    assert parsed.values == {"loss": 1.25, "training_time_s": 2.0}
    assert parsed.warnings == [
        "extra metric 'best_model' ignored because value is not numeric (type str)"
    ]


def test_parse_metrics_rejects_nonnumeric_expected_metric(tmp_path) -> None:
    artifacts = tmp_path
    (artifacts / "metrics.json").write_text(
        json.dumps({"loss": "bad"}),
        encoding="utf-8",
    )

    parsed = parse_metrics(artifacts, [{"name": "loss"}])

    assert parsed.ok is False
    assert "metric 'loss': value 'bad' is not numeric (type str)" in parsed.errors


def test_parse_metrics_canonicalizes_treatment_nested_metrics(tmp_path) -> None:
    artifacts = tmp_path
    (artifacts / "metrics.json").write_text(
        json.dumps(
            {
                "standard_backprop": {
                    "final_perplexity": 25.0,
                    "training_time_seconds": 14.0,
                    "peak_memory_mb": 512.0,
                },
                "diffusionblocks": {
                    "final_perplexity": 18.0,
                    "training_time_seconds": 11.0,
                    "peak_memory_mb": 384.0,
                },
            }
        ),
        encoding="utf-8",
    )

    parsed = parse_metrics(
        artifacts,
        [
            {"name": "final_perplexity"},
            {"name": "training_time_seconds"},
            {"name": "peak_memory_mb"},
        ],
    )

    assert parsed.ok is True
    assert parsed.values["final_perplexity"] == 18.0
    assert parsed.values["training_time_seconds"] == 11.0
    assert parsed.values["peak_memory_mb"] == 384.0
    assert parsed.values["standard_backprop.final_perplexity"] == 25.0
    assert parsed.values["diffusionblocks.final_perplexity"] == 18.0
    assert "canonicalized flat metrics from nested group 'diffusionblocks'" in parsed.warnings
