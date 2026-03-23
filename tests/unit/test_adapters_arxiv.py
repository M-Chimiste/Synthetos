"""Unit tests for libs.adapters.arxiv."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx

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


def test_build_params_omits_category_set_for_global_incremental_sync():
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig())
    params = adapter._build_params("", "2024-01-01", "2024-01-31", None)

    assert params["verb"] == "ListRecords"
    assert params["metadataPrefix"] == "arXiv"
    assert "set" not in params


# --- Retry logic tests ---


def test_request_retries_on_transient_failure_then_succeeds():
    """_request retries on HTTPError and returns response on eventual success."""
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig(request_interval=0.0))
    adapter._last_request_time = 0

    call_count = 0

    def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, text="<ok/>", request=httpx.Request("GET", "http://t"))

    with (
        patch("libs.adapters.arxiv.adapter.httpx.get", side_effect=mock_get),
        patch("libs.adapters.arxiv.adapter.time.sleep"),
    ):
        result = adapter._request({"verb": "ListRecords"})

    assert result == "<ok/>"
    assert call_count == 3


def test_request_returns_none_after_retries_exhausted():
    """_request returns None when all retry attempts fail."""
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig(request_interval=0.0))
    adapter._last_request_time = 0

    def mock_get(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    with (
        patch("libs.adapters.arxiv.adapter.httpx.get", side_effect=mock_get),
        patch("libs.adapters.arxiv.adapter.time.sleep"),
    ):
        result = adapter._request({"verb": "ListRecords"})

    assert result is None


# --- Multi-category tests ---


def test_search_multi_category_harvests_each_and_deduplicates():
    """Multi-category search calls _harvest_category per category and dedupes."""
    xml_text = (FIXTURES_DIR / "arxiv_oai_pmh_response.xml").read_text()
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig(request_interval=0.0))

    call_categories: list[str] = []
    original_harvest = adapter._harvest_category

    def tracking_harvest(category, query, max_results):
        call_categories.append(category)
        return original_harvest(category, query, max_results)

    # Mock _request to return same XML for any category
    with (
        patch.object(adapter, "_request", return_value=xml_text),
        patch.object(adapter, "_harvest_category", side_effect=tracking_harvest),
    ):
        query = SourceQuery(categories=["cs.LG", "cs.CL"], max_results=100)
        records = adapter.search(query)

    assert call_categories == ["cs.LG", "cs.CL"]
    # Records should be deduplicated by external_id
    ids = [r.external_id for r in records]
    assert len(ids) == len(set(ids))


def test_search_single_category_uses_direct_harvest():
    """Single category search calls _harvest_category once."""
    adapter = ArxivMetadataAdapter(ArxivAdapterConfig(request_interval=0.0))

    with patch.object(adapter, "_harvest_category", return_value=[]) as mock_h:
        query = SourceQuery(categories=["cs.LG"], max_results=10)
        adapter.search(query)

    mock_h.assert_called_once_with("cs.LG", query, 10)
