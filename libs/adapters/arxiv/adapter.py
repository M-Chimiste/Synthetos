"""arXiv OAI-PMH metadata adapter.

Harvests metadata from the arXiv OAI-PMH endpoint with rate-limit
compliance (≤1 request per 3 seconds), resumption token support,
and optional category/date filtering.

References: project_docs/m-chimiste-arxiv-harvester-example.txt
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx
import structlog

from libs.adapters.literature import LiteratureSourceAdapter, RawPaperRecord, SourceQuery

log = structlog.get_logger(__name__)

OAI_BASE_URL = "https://export.arxiv.org/oai2"
OAI_NAMESPACE = "{http://www.openarchives.org/OAI/2.0/}"
ARXIV_NAMESPACE = "{http://arxiv.org/OAI/arXiv/}"
MIN_REQUEST_INTERVAL = 3.0  # ArXiv rate-limit policy


class ArxivAdapterConfig:
    def __init__(
        self,
        base_url: str = OAI_BASE_URL,
        timeout: int = 60,
        max_results: int | None = None,
        request_interval: float = MIN_REQUEST_INTERVAL,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_results = max_results
        self.request_interval = max(request_interval, MIN_REQUEST_INTERVAL)


class ArxivMetadataAdapter(LiteratureSourceAdapter):
    """Adapter that harvests arXiv paper metadata via OAI-PMH."""

    def __init__(self, config: ArxivAdapterConfig | None = None):
        self.config = config or ArxivAdapterConfig()
        self._last_request_time: float = 0

    def search(self, query: SourceQuery) -> list[RawPaperRecord]:
        """Search arXiv metadata via OAI-PMH ListRecords."""
        records: list[RawPaperRecord] = []
        resumption_token: str | None = None
        max_results = query.max_results or self.config.max_results

        category = query.categories[0] if query.categories else "cs"

        while True:
            params = self._build_params(
                category=category,
                date_from=query.date_from,
                date_until=query.date_until,
                resumption_token=resumption_token,
            )

            xml_text = self._request(params)
            if xml_text is None:
                break

            batch, resumption_token = self._parse_response(xml_text, query)
            records.extend(batch)

            log.info(
                "arxiv_batch_received",
                batch_size=len(batch),
                total_so_far=len(records),
                has_resumption=resumption_token is not None,
            )

            if max_results and len(records) >= max_results:
                records = records[:max_results]
                break

            if not resumption_token:
                break

        return records

    def _build_params(
        self,
        category: str,
        date_from: str | None,
        date_until: str | None,
        resumption_token: str | None,
    ) -> dict[str, str]:
        if resumption_token:
            return {
                "verb": "ListRecords",
                "resumptionToken": resumption_token,
            }
        params: dict[str, str] = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "set": f"{category}",
        }
        if date_from:
            params["from"] = date_from
        if date_until:
            params["until"] = date_until
        return params

    def _request(self, params: dict[str, str]) -> str | None:
        """Make a rate-limited HTTP request to the OAI-PMH endpoint."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.config.request_interval:
            time.sleep(self.config.request_interval - elapsed)

        try:
            resp = httpx.get(
                self.config.base_url,
                params=params,
                timeout=self.config.timeout,
                headers={"User-Agent": "Synthetos-ML-Lab/1.0"},
            )
            self._last_request_time = time.monotonic()
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            log.warning("arxiv_oai_request_failed", error=str(exc))
            return None

    def _parse_response(
        self, xml_text: str, query: SourceQuery,
    ) -> tuple[list[RawPaperRecord], str | None]:
        """Parse OAI-PMH XML and extract RawPaperRecords."""
        records: list[RawPaperRecord] = []
        resumption_token: str | None = None

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.warning("arxiv_xml_parse_error", error=str(exc))
            return records, None

        list_records = root.find(f"{OAI_NAMESPACE}ListRecords")
        if list_records is None:
            return records, None

        for record_elem in list_records.findall(f"{OAI_NAMESPACE}record"):
            paper = self._parse_record(record_elem, query)
            if paper is not None:
                records.append(paper)

        token_elem = list_records.find(f"{OAI_NAMESPACE}resumptionToken")
        if token_elem is not None and token_elem.text:
            resumption_token = token_elem.text.strip()

        return records, resumption_token

    def _parse_record(
        self, record_elem: ET.Element, query: SourceQuery,
    ) -> RawPaperRecord | None:
        """Parse a single OAI-PMH record element into a RawPaperRecord."""
        metadata = record_elem.find(f"{OAI_NAMESPACE}metadata")
        if metadata is None:
            return None

        arxiv = metadata.find(f"{ARXIV_NAMESPACE}arXiv")
        if arxiv is None:
            return None

        arxiv_id = _text(arxiv, f"{ARXIV_NAMESPACE}id")
        if not arxiv_id:
            return None

        title = _text(arxiv, f"{ARXIV_NAMESPACE}title", "")
        abstract = _text(arxiv, f"{ARXIV_NAMESPACE}abstract", "")
        categories_str = _text(arxiv, f"{ARXIV_NAMESPACE}categories", "")
        categories = categories_str.split() if categories_str else []
        created = _text(arxiv, f"{ARXIV_NAMESPACE}created")
        updated = _text(arxiv, f"{ARXIV_NAMESPACE}updated")
        doi = _text(arxiv, f"{ARXIV_NAMESPACE}doi")

        # Filter by subcategories if specified
        if query.categories and len(query.categories) > 1:
            subcats = set(query.categories)
            if not subcats.intersection(categories):
                return None

        authors = _parse_authors(arxiv)

        return RawPaperRecord(
            external_id=arxiv_id,
            title=title.strip(),
            abstract=abstract.strip() if abstract else None,
            authors=authors,
            categories=categories,
            publication_date=created,
            source_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            source_type="arxiv",
            metadata_extra={
                k: v
                for k, v in {"doi": doi, "updated": updated}.items()
                if v is not None
            },
        )


def _text(parent: ET.Element, tag: str, default: str | None = None) -> str | None:
    elem = parent.find(tag)
    if elem is not None and elem.text:
        return elem.text.strip()
    return default


def _parse_authors(arxiv: ET.Element) -> list[str]:
    authors: list[str] = []
    authors_elem = arxiv.find(f"{ARXIV_NAMESPACE}authors")
    if authors_elem is None:
        return authors
    for author in authors_elem.findall(f"{ARXIV_NAMESPACE}author"):
        keyname = _text(author, f"{ARXIV_NAMESPACE}keyname", "")
        forenames = _text(author, f"{ARXIV_NAMESPACE}forenames", "")
        name = f"{forenames} {keyname}".strip()
        if name:
            authors.append(name)
    return authors
