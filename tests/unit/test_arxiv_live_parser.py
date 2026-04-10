"""Tests for the arXiv live Atom parser (offline fixture)."""

from __future__ import annotations

from libs.adapters.sources.arxiv_live import _build_search_query, _parse_atom
from libs.adapters.sources.base import SourceQuery

_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <title>Attention Is Almost All You Need</title>
    <summary>We propose a small refinement to attention.</summary>
    <published>2023-01-30T18:00:00Z</published>
    <author><name>Doe, Jane</name></author>
    <author><name>Smith, John</name></author>
    <category term="cs.LG"/>
    <category term="cs.CL"/>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2301.12345v1"/>
    <link title="pdf" href="http://arxiv.org/pdf/2301.12345v1"/>
    <arxiv:doi>10.5555/abc.def</arxiv:doi>
    <arxiv:journal_ref>NeurIPS 2023</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <title>Another Paper</title>
    <summary>Some abstract text.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Solo</name></author>
    <category term="stat.ML"/>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2401.00001v2"/>
  </entry>
</feed>
"""


def test_parse_atom_extracts_two_entries() -> None:
    hits = _parse_atom(_FIXTURE)
    assert len(hits) == 2

    h0 = hits[0]
    assert h0.source == "arxiv_live"
    assert h0.external_id == "2301.12345v1"
    assert h0.title == "Attention Is Almost All You Need"
    assert "small refinement" in h0.abstract
    assert h0.authors == ["Doe, Jane", "Smith, John"]
    assert h0.categories == ["cs.LG", "cs.CL"]
    assert h0.doi == "10.5555/abc.def"
    assert h0.venue == "NeurIPS 2023"
    assert h0.pdf_url == "http://arxiv.org/pdf/2301.12345v1"
    assert h0.year == 2023


def test_parse_atom_handles_missing_optional_fields() -> None:
    hits = _parse_atom(_FIXTURE)
    h1 = hits[1]
    assert h1.doi is None
    assert h1.venue is None
    assert h1.pdf_url is None


def test_build_search_query_combines_text_and_categories() -> None:
    q = SourceQuery(text="diffusion models", top_k=10, categories=["cs.LG", "cs.CV"])
    s = _build_search_query(q)
    assert 'all:"diffusion models"' in s
    assert "cat:cs.LG" in s
    assert "cat:cs.CV" in s
    assert " AND " in s
