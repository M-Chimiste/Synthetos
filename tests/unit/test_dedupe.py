"""Tests for source dedupe key generation and merging."""

from __future__ import annotations

from libs.adapters.sources.base import SourceHit
from libs.adapters.sources.dedupe import dedupe_hits, dedupe_key, merge_hits


def _hit(**overrides) -> SourceHit:
    base = {
        "source": "internal_corpus",
        "external_id": "1234.5678",
        "title": "A Brief History of Time",
        "abstract": "Cosmology textbook abstract.",
        "authors": ["Hawking, Stephen"],
        "categories": ["physics.gen-ph"],
    }
    base.update(overrides)
    return SourceHit.model_validate(base)


def test_dedupe_key_uses_doi_when_present() -> None:
    h = _hit(doi="https://doi.org/10.1000/XYZ")
    assert dedupe_key(h) == "doi:10.1000/xyz"


def test_dedupe_key_falls_back_to_arxiv_for_arxiv_sources() -> None:
    h = _hit(source="arxiv_live", external_id="2301.12345v3", doi=None)
    assert dedupe_key(h) == "arxiv:2301.12345"


def test_dedupe_key_falls_back_to_title_hash() -> None:
    h = _hit(source="other", doi=None)
    key = dedupe_key(h)
    assert key.startswith("title:")
    # Same title + first author => same key
    assert dedupe_key(_hit(source="other", external_id="other-id", doi=None)) == key


def test_dedupe_collapses_internal_and_live_for_same_doi() -> None:
    internal = _hit(doi="10.1000/XYZ", embedding=[0.1] * 768)
    live = _hit(source="arxiv_live", external_id="2301.99999", doi="10.1000/XYZ")
    deduped, dropped = dedupe_hits([internal, live])
    assert len(deduped) == 1
    assert dropped == 1
    assert deduped[0].embedding is not None  # internal embedding kept


def test_merge_hits_prefers_primary_but_fills_missing() -> None:
    primary = _hit(doi=None, venue=None)
    secondary = _hit(doi="10.1/abc", venue="NeurIPS 2023", embedding=[0.2] * 768)
    merged = merge_hits(primary, secondary)
    assert merged.doi == "10.1/abc"
    assert merged.venue == "NeurIPS 2023"
    # primary had no embedding -> takes secondary's
    assert merged.embedding == [0.2] * 768
