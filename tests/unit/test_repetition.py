"""Tests for repetition detection in autonomous loops."""

from __future__ import annotations

from unittest.mock import MagicMock

from libs.orchestration.repetition import (
    compute_spec_hash,
)


class TestComputeSpecHash:
    def test_deterministic(self) -> None:
        spec = MagicMock()
        spec.hypothesis_card_id = 1
        spec.method_description = "Train a ResNet-18"
        spec.metrics = [{"name": "accuracy"}, {"name": "loss"}]
        spec.controls = [{"name": "lr", "value": 0.01}]
        spec.datasets = [{"name": "cifar10"}]

        h1 = compute_spec_hash(spec)
        h2 = compute_spec_hash(spec)
        assert h1 == h2

    def test_different_method_different_hash(self) -> None:
        spec1 = MagicMock()
        spec1.hypothesis_card_id = 1
        spec1.method_description = "Train a ResNet-18"
        spec1.metrics = [{"name": "accuracy"}]
        spec1.controls = []
        spec1.datasets = []

        spec2 = MagicMock()
        spec2.hypothesis_card_id = 1
        spec2.method_description = "Train a VGG-16"
        spec2.metrics = [{"name": "accuracy"}]
        spec2.controls = []
        spec2.datasets = []

        assert compute_spec_hash(spec1) != compute_spec_hash(spec2)

    def test_different_hypothesis_different_hash(self) -> None:
        spec1 = MagicMock()
        spec1.hypothesis_card_id = 1
        spec1.method_description = "Train"
        spec1.metrics = []
        spec1.controls = []
        spec1.datasets = []

        spec2 = MagicMock()
        spec2.hypothesis_card_id = 2
        spec2.method_description = "Train"
        spec2.metrics = []
        spec2.controls = []
        spec2.datasets = []

        assert compute_spec_hash(spec1) != compute_spec_hash(spec2)

    def test_handles_none_fields(self) -> None:
        spec = MagicMock()
        spec.hypothesis_card_id = 1
        spec.method_description = None
        spec.metrics = None
        spec.controls = None
        spec.datasets = None

        h = compute_spec_hash(spec)
        assert isinstance(h, str)
        assert len(h) == 16
