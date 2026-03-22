"""Full-text fetcher for escalated papers.

Implements the metadata-first principle: HTML (ar5iv) first,
PDF fallback only when necessary. Uses markitdown for PDF-to-markdown
conversion so downstream operators work with clean text.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import structlog
from markitdown import MarkItDown

from libs.adapters.literature import FetchResult

log = structlog.get_logger(__name__)


class FulltextFetcher:
    """Fetches full text for papers that have been escalated for deeper reading."""

    def __init__(self, artifact_dir: Path, timeout: int = 30):
        self.artifact_dir = artifact_dir
        self.timeout = timeout
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._markitdown = MarkItDown()

    def fetch_html(self, arxiv_id: str, reason: str) -> FetchResult | None:
        """Try to fetch HTML from ar5iv (HTML version of arXiv papers)."""
        url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        try:
            resp = httpx.get(
                url, timeout=self.timeout, follow_redirects=True,
                headers={"User-Agent": "Synthetos-ML-Lab/1.0"},
            )
            resp.raise_for_status()
            safe_id = arxiv_id.replace("/", "_")
            path = self.artifact_dir / f"{safe_id}.html"
            path.write_bytes(resp.content)
            log.info("fulltext_html_fetched", arxiv_id=arxiv_id, bytes=len(resp.content))
            return FetchResult(
                content_type="html",
                artifact_path=str(path),
                byte_count=len(resp.content),
                fetch_reason=reason,
            )
        except httpx.HTTPError as exc:
            log.warning("fulltext_html_fetch_failed", arxiv_id=arxiv_id, error=str(exc))
            return None

    def fetch_pdf(self, pdf_url: str, paper_id: str, reason: str) -> FetchResult | None:
        """Fetch PDF, convert to markdown via markitdown, and store both."""
        try:
            resp = httpx.get(
                pdf_url, timeout=self.timeout, follow_redirects=True,
                headers={"User-Agent": "Synthetos-ML-Lab/1.0"},
            )
            resp.raise_for_status()
            safe_id = paper_id.replace("/", "_")
            pdf_path = self.artifact_dir / f"{safe_id}.pdf"
            pdf_path.write_bytes(resp.content)

            # Convert PDF to markdown using markitdown
            md_path = self.artifact_dir / f"{safe_id}.md"
            try:
                result = self._markitdown.convert(str(pdf_path))
                md_path.write_text(result.text_content, encoding="utf-8")
                artifact_path = str(md_path)
                byte_count = len(result.text_content.encode("utf-8"))
                log.info(
                    "fulltext_pdf_converted",
                    paper_id=paper_id,
                    pdf_bytes=len(resp.content),
                    md_bytes=byte_count,
                )
            except Exception as conv_exc:
                log.warning(
                    "fulltext_pdf_conversion_failed",
                    paper_id=paper_id,
                    error=str(conv_exc),
                )
                # Fall back to raw PDF path if conversion fails
                artifact_path = str(pdf_path)
                byte_count = len(resp.content)

            return FetchResult(
                content_type="pdf",
                artifact_path=artifact_path,
                byte_count=byte_count,
                fetch_reason=reason,
            )
        except httpx.HTTPError as exc:
            log.warning("fulltext_pdf_fetch_failed", paper_id=paper_id, error=str(exc))
            return None
