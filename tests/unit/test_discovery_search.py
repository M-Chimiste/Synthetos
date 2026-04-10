"""Tests for discovery search fusion behavior."""

from __future__ import annotations

import pytest

from libs.adapters.sources.base import SourceHit
from libs.discovery.operators import search as search_operator


class _FakeAsyncSession:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _hit(**overrides) -> SourceHit:
    base = {
        "source": "internal_corpus",
        "external_id": "1234.5678",
        "title": "Paper A",
        "abstract": "Abstract A",
        "authors": ["Doe, Jane"],
        "categories": ["cs.LG"],
    }
    base.update(overrides)
    return SourceHit.model_validate(base)


@pytest.mark.asyncio
async def test_run_search_fuses_rankings_across_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_internal(_db: object, _query: object) -> list[SourceHit]:
        return [
            _hit(external_id="1111.1111", title="Shared Paper", first_stage_score=0.01),
            _hit(external_id="2222.2222", title="Internal Only", first_stage_score=0.009),
        ]

    async def fake_search_external(_query: object) -> list[SourceHit]:
        return [
            _hit(
                source="arxiv_live",
                external_id="3333.3333",
                title="External Only",
                first_stage_score=1.0,
            ),
            _hit(
                source="arxiv_live",
                external_id="1111.1111v2",
                title="Shared Paper",
                first_stage_score=0.5,
            ),
        ]

    monkeypatch.setattr(search_operator, "_search_internal", fake_search_internal)
    monkeypatch.setattr(search_operator, "_search_external", fake_search_external)
    monkeypatch.setattr(search_operator, "get_async_session_factory", lambda: _FakeAsyncSession)

    hits, counts = await search_operator._run_search(
        profile_text="shared paper",
        categories=["cs.LG"],
        scope={"internal_corpus": True, "arxiv_live": True},
        budget={},
    )

    by_title = {hit.title: hit for hit in hits}
    assert counts["deduped"] == 3
    assert counts["dropped_duplicates"] == 1
    assert counts["sources_fused"] == 2
    assert by_title["Shared Paper"].source == "internal_corpus"
    assert by_title["Shared Paper"].first_stage_score is not None
    assert by_title["External Only"].first_stage_score is not None
    assert by_title["Internal Only"].first_stage_score is not None
    assert by_title["Shared Paper"].first_stage_score > by_title["External Only"].first_stage_score
    assert 0.0 <= by_title["External Only"].first_stage_score <= 1.0
