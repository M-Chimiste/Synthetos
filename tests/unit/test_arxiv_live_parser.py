"""Tests for the arXiv live Atom parser (offline fixture)."""

from __future__ import annotations

from libs.adapters.sources.arxiv_live import (
    _build_request_params,
    _build_search_query,
    _extract_arxiv_ids,
    _parse_arxiv_html,
    _parse_atom,
)
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

_HTML_FIXTURE = """
<html>
  <body>
    <h1 class="ltx_title ltx_title_document">DiffusionBlocks: Block-wise Training</h1>
    <div class="ltx_abstract">
      <h6>Abstract</h6>
      <p>Independent block training reduces activation memory.</p>
    </div>
  </body>
</html>
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


def test_extract_arxiv_ids_from_url_and_text() -> None:
    ids = _extract_arxiv_ids("Use https://arxiv.org/html/2506.14202v3 and 2401.00001")
    assert ids == ["2506.14202v3", "2401.00001"]


def test_build_request_params_uses_id_list_for_exact_arxiv_references() -> None:
    params = _build_request_params(
        SourceQuery(text="https://arxiv.org/html/2506.14202v3", top_k=10)
    )
    assert params["id_list"] == "2506.14202v3"
    assert "search_query" not in params


def test_parse_arxiv_html_fallback_extracts_metadata() -> None:
    hit = _parse_arxiv_html(_HTML_FIXTURE, arxiv_id="2506.14202v3")

    assert hit is not None
    assert hit.external_id == "2506.14202v3"
    assert hit.title == "DiffusionBlocks: Block-wise Training"
    assert "activation memory" in hit.abstract
    assert hit.year == 2025
