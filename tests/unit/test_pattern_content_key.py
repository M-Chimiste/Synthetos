"""Tests for canonical pattern content-key stability."""

from __future__ import annotations

import pytest

from libs.patterns import content_key


class TestStability:
    def test_failure_key_normalizes_whitespace_and_case(self) -> None:
        a = content_key.failure_key(
            failure_class="OOM", root_cause="GPU  out of memory"
        )
        b = content_key.failure_key(
            failure_class="oom", root_cause="gpu out of memory"
        )
        assert a == b

    def test_failure_key_differentiates_class(self) -> None:
        a = content_key.failure_key(failure_class="oom", root_cause="x")
        b = content_key.failure_key(failure_class="timeout", root_cause="x")
        assert a != b

    def test_remediation_key_orders_components(self) -> None:
        a = content_key.remediation_key(
            failure_class="oom", strategy="reduce_batch", outcome="retry_created"
        )
        b = content_key.remediation_key(
            failure_class="oom", strategy="reduce_batch", outcome="retry_created"
        )
        assert a == b

    def test_retrieval_heuristic_key_sorts_parameters(self) -> None:
        a = content_key.retrieval_heuristic_key(
            heuristic_kind="loop_pivot", parameters={"a": 1, "b": 2}
        )
        b = content_key.retrieval_heuristic_key(
            heuristic_kind="loop_pivot", parameters={"b": 2, "a": 1}
        )
        assert a == b

    def test_dispatch_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError):
            content_key.key_for("not_a_type", failure_class="x", root_cause="y")

    def test_dispatch_failure(self) -> None:
        direct = content_key.failure_key(failure_class="oom", root_cause="x")
        via = content_key.key_for("failure", failure_class="oom", root_cause="x")
        assert direct == via
