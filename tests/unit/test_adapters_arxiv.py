"""Unit tests for libs.adapters.arxiv."""

from __future__ import annotations

from pathlib import Path

from libs.adapters.arxiv.adapter import ArxivAdapterConfig, ArxivMetadataAdapter
from libs.adapters.literature import SourceQuery

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_parse_oai_pmh_xml():
    xml_text = (FIXTURES_DIR / "arxiv_oai_pmh_response.xml").read_text()
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig())
    query = SourceQuery(categories=["cs"], max_results=100)
    records, token = adapter._parse_response(xml_text, query)

    assert len(records) == 2
    assert records[0].external_id == "2401.00001"
    assert records[0].title == "A Novel Approach to Neural Architecture Search"
    assert "Alice Smith" in records[0].authors
    assert "Bob Jones" in records[0].authors
    assert records[0].source_type == "arxiv"
    assert records[0].source_url == "https://arxiv.org/abs/2401.00001"
    assert records[0].pdf_url == "https://arxiv.org/pdf/2401.00001"
    assert "cs.LG" in records[0].categories
    assert "cs.AI" in records[0].categories

    assert records[1].external_id == "2401.00002"
    assert "Carol White" in records[1].authors

    # No resumption token in this fixture
    assert token is None


def test_parse_oai_pmh_subcategory_filter():
    xml_text = (FIXTURES_DIR / "arxiv_oai_pmh_response.xml").read_text()
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig())
    # Filter to only cs.CL papers
    query = SourceQuery(categories=["cs", "cs.CL"], max_results=100)
    records, _ = adapter._parse_response(xml_text, query)

    # Only the second record has cs.CL
    assert len(records) == 1
    assert records[0].external_id == "2401.00002"
