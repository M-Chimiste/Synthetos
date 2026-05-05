"""Tests for incremental arXiv corpus update helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.cli.commands import corpus

_INCREMENTAL_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2603.12345v2</id>
    <updated>2026-03-28T00:00:00Z</updated>
    <published>2026-03-27T18:00:00Z</published>
    <title>Fresh Universal Abstracts</title>
    <summary>
      A new abstract from the live arXiv feed.
    </summary>
    <author><name>Doe, Jane</name></author>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="math.OC"/>
    <link rel="alternate" href="http://arxiv.org/abs/2603.12345v2"/>
    <link title="pdf" href="http://arxiv.org/pdf/2603.12345v2"/>
    <arxiv:doi>10.5555/live.1</arxiv:doi>
    <arxiv:comment>12 pages</arxiv:comment>
    <arxiv:journal_ref>Test Journal</arxiv:journal_ref>
  </entry>
</feed>
"""


def test_incremental_search_query_uses_submitted_date_without_category_filter() -> None:
    start = datetime(2026, 3, 26, 17, 59, tzinfo=UTC)
    end = datetime(2026, 5, 5, 13, 48, tzinfo=UTC)

    query = corpus._build_incremental_search_query(start, end)

    assert query == "submittedDate:[202603261759 TO 202605051348]"
    assert "cat:" not in query


def test_parse_incremental_feed_strips_version_and_preserves_all_categories() -> None:
    records = corpus._parse_arxiv_incremental_feed(_INCREMENTAL_FEED)

    assert len(records) == 1
    record = records[0]
    assert record["arxiv_id"] == "2603.12345"
    assert record["title"] == "Fresh Universal Abstracts"
    assert record["abstract"] == "A new abstract from the live arXiv feed."
    assert record["authors"] == ["Doe, Jane"]
    assert record["categories"] == ["cs.LG", "math.OC"]
    assert record["created_date"] == "2026-03-27T18:00:00+00:00"
    assert record["updated_date"] == "2026-03-28T00:00:00+00:00"
    assert record["doi"] == "10.5555/live.1"
    assert record["pdf_url"] == "http://arxiv.org/pdf/2603.12345v2"
    assert record["raw_metadata"]["primary_category"] == "cs.LG"
    assert record["raw_metadata"]["journal_ref"] == "Test Journal"
    assert record["embedding_model_id"] == corpus._EXPECTED_MODEL
    assert record["embedding"] is None
