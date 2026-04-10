"""Live arXiv API source adapter.

Hits ``http://export.arxiv.org/api/query`` with an Atom request and parses
the response with the stdlib XML parser.  Honors arXiv's published 3-second
minimum interval between requests via a tiny token bucket.

This adapter only returns metadata -- no embeddings, no full text.  Live
results enter discovery alongside internal corpus rows and are deduplicated
by :func:`libs.adapters.sources.dedupe.dedupe_key`.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from libs.adapters.sources.base import SourceHit, SourceQuery
from libs.core.logging import get_logger

log = get_logger(__name__)


_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_DEFAULT_BASE_URL = "http://export.arxiv.org/api/query"
_MIN_REQUEST_INTERVAL_S = 3.0


def _build_search_query(query: SourceQuery) -> str:
    """Translate a SourceQuery into the arXiv ``search_query`` parameter."""
    text_clause = f'all:"{query.text}"'
    parts: list[str] = [text_clause]

    if query.categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in query.categories)
        parts.append(f"({cat_clause})")

    return " AND ".join(parts)


def _parse_entry(entry: ET.Element) -> SourceHit | None:
    def _text(tag: str, ns: str = "atom") -> str | None:
        el = entry.find(f"{ns}:{tag}", _ATOM_NS)
        if el is None or el.text is None:
            return None
        return el.text.strip()

    arxiv_url = _text("id")
    if not arxiv_url:
        return None
    # arxiv_url looks like ``http://arxiv.org/abs/2301.12345v1``
    arxiv_id = arxiv_url.rsplit("/", 1)[-1]
    title = _text("title") or ""
    abstract = _text("summary") or ""

    authors: list[str] = []
    for author_el in entry.findall("atom:author", _ATOM_NS):
        name_el = author_el.find("atom:name", _ATOM_NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    categories: list[str] = []
    for cat_el in entry.findall("atom:category", _ATOM_NS):
        term = cat_el.get("term")
        if term:
            categories.append(term)

    published: datetime | None = None
    published_str = _text("published")
    if published_str:
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except ValueError:
            published = None

    pdf_url: str | None = None
    source_url: str | None = arxiv_url
    for link_el in entry.findall("atom:link", _ATOM_NS):
        rel = link_el.get("rel")
        title_attr = link_el.get("title")
        href = link_el.get("href")
        if title_attr == "pdf" and href:
            pdf_url = href
        elif rel == "alternate" and href:
            source_url = href

    doi = _text("doi", ns="arxiv")
    journal_ref = _text("journal_ref", ns="arxiv")

    year = published.year if published else None

    return SourceHit(
        source="arxiv_live",
        external_id=arxiv_id,
        title=title.replace("\n", " ").strip(),
        abstract=abstract.replace("\n", " ").strip(),
        authors=authors,
        categories=categories,
        venue=journal_ref,
        year=year,
        published_at=published,
        doi=doi,
        source_url=source_url,
        pdf_url=pdf_url,
    )


def _parse_atom(payload: bytes) -> list[SourceHit]:
    root = ET.fromstring(payload)
    hits: list[SourceHit] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        hit = _parse_entry(entry)
        if hit is not None:
            hits.append(hit)
    return hits


class ArxivLiveAdapter:
    """Async client for the arXiv Atom API.

    A class-level lock + monotonic clock enforces the 3-second minimum
    interval across all instances within a process.
    """

    name = "arxiv_live"

    _last_request_at: float = 0.0
    _rate_lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url
        self._client = httpx.AsyncClient(timeout=timeout)
        self._max_retries = max_retries

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - ArxivLiveAdapter._last_request_at
            wait_for = _MIN_REQUEST_INTERVAL_S - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            ArxivLiveAdapter._last_request_at = time.monotonic()

    async def search(self, query: SourceQuery) -> list[SourceHit]:
        params: dict[str, Any] = {
            "search_query": _build_search_query(query),
            "start": 0,
            "max_results": min(query.top_k, 100),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        payload: bytes = b""
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
            reraise=True,
        ):
            with attempt:
                await self._wait_for_rate_limit()
                resp = await self._client.get(self._base_url, params=params)
                if resp.status_code in (429, 503):
                    log.warning(
                        "arxiv_live.throttled",
                        status=resp.status_code,
                    )
                    raise httpx.HTTPStatusError("throttled", request=resp.request, response=resp)
                resp.raise_for_status()
                payload = resp.content

        hits = _parse_atom(payload)
        log.info(
            "arxiv_live.search_done",
            query=query.text[:100],
            results=len(hits),
        )
        # Annotate first-stage score from rank position so the fusion has
        # something to work with even though arxiv returns relevance order.
        for idx, hit in enumerate(hits):
            hit.first_stage_score = 1.0 / (idx + 1)
        return hits

    async def close(self) -> None:
        await self._client.aclose()
