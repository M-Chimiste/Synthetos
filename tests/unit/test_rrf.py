"""Tests for reciprocal rank fusion."""

from __future__ import annotations

from libs.discovery.ranking import normalize_scores, rrf_fuse


def test_rrf_single_list_matches_reciprocal_rank() -> None:
    fused = rrf_fuse([["a", "b", "c"]], k=60)
    assert fused["a"] > fused["b"] > fused["c"]
    # Top item is 1/(60+1)
    assert abs(fused["a"] - (1 / 61)) < 1e-9


def test_rrf_two_lists_combine_scores() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]], k=60)
    # 'a' appears at rank 1 and rank 2 -> larger combined score than 'd' which only appears once
    assert fused["a"] > fused["d"]
    # 'a' (1, 2) and 'b' (2, 1) have the same combined score
    assert abs(fused["a"] - fused["b"]) < 1e-12


def test_rrf_handles_empty_input() -> None:
    assert rrf_fuse([]) == {}
    assert rrf_fuse([[], []]) == {}


def test_rrf_documents_only_in_one_list() -> None:
    fused = rrf_fuse([["a", "b"], ["c"]], k=10)
    assert set(fused) == {"a", "b", "c"}
    # 'a' rank 1 in list 0
    assert fused["a"] == 1 / 11
    # 'c' rank 1 in list 1
    assert fused["c"] == 1 / 11


def test_normalize_scores_minmax() -> None:
    norm = normalize_scores({"a": 10.0, "b": 5.0, "c": 0.0})
    assert norm["a"] == 1.0
    assert norm["c"] == 0.0
    assert 0.0 < norm["b"] < 1.0


def test_normalize_scores_handles_constant() -> None:
    assert normalize_scores({"a": 1.0, "b": 1.0}) == {"a": 1.0, "b": 1.0}


def test_normalize_scores_handles_empty() -> None:
    assert normalize_scores({}) == {}
