"""Full-text ingestion orchestration.

Implements the HTML-first → PDF fallback fetch strategy.  On success the
normalized document is persisted to ``ingested_documents`` so downstream
operators can read from it without re-fetching.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.adapters.ingestion.base import IngestionResult
from libs.adapters.ingestion.html_fetcher import HtmlFetcher
from libs.adapters.ingestion.pdf_processor import PdfProcessor
from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.storage.models.analysis import IngestedDocument

log = get_logger("analysis.ingestion")


async def fetch_and_persist(
    db: Session,
    *,
    analysis_session_id: UUID,
    paper_card_id: UUID,
    paper_url: str,
    pdf_url: str | None,
    quality_threshold: float = 0.5,
) -> IngestedDocument:
    """Fetch full text (HTML-first, PDF fallback) and persist the result.

    Returns the persisted ``IngestedDocument`` row.
    """
    result: IngestionResult | None = None
    html_fetcher = HtmlFetcher()
    pdf_processor = PdfProcessor()

    try:
        # 1. Try HTML first
        try:
            html_result = await html_fetcher.fetch_fulltext(paper_url, pdf_url)
            if html_result.quality_assessment.quality_score >= quality_threshold:
                result = html_result
                log.info(
                    "html_fetch_accepted",
                    quality=html_result.quality_assessment.quality_score,
                )
            else:
                log.info(
                    "html_quality_below_threshold",
                    quality=html_result.quality_assessment.quality_score,
                    threshold=quality_threshold,
                )
        except Exception:
            log.info("html_fetch_failed", exc_info=True)

        # 2. Fall back to PDF if HTML failed or quality was low
        if result is None and pdf_url:
            try:
                result = await pdf_processor.fetch_fulltext(paper_url, pdf_url)
                log.info(
                    "pdf_fallback_used",
                    quality=result.quality_assessment.quality_score,
                )
            except Exception:
                log.warning("pdf_fetch_failed", exc_info=True)

        # 3. If both failed, try PDF with paper_url as last resort
        if result is None:
            result = await pdf_processor.fetch_fulltext(paper_url, paper_url)

    finally:
        await html_fetcher.close()
        await pdf_processor.close()

    # Persist the ingested document
    content_hash = hashlib.sha256(result.content.encode()).hexdigest()

    doc = IngestedDocument(
        id=uuid7(),
        analysis_session_id=analysis_session_id,
        paper_card_id=paper_card_id,
        fetch_method=result.fetch_method,
        source_url=result.source_url,
        raw_content=result.content,
        normalized_sections=[s.model_dump() for s in result.normalized_sections],
        normalized_figures=[f.model_dump() for f in result.normalized_figures],
        normalized_tables=[t.model_dump() for t in result.normalized_tables],
        normalized_equations=[e.model_dump() for e in result.normalized_equations],
        quality_assessment=result.quality_assessment.model_dump(),
        fetch_duration_ms=result.fetch_duration_ms,
        content_hash=content_hash,
        created_at=utcnow(),
    )
    db.add(doc)
    db.flush()

    return doc
