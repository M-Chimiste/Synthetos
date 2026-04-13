"""PDF fallback ingestion adapter using Docling.

Used when HTML is unavailable or HTML quality is below the configured threshold.
Downloads the PDF via httpx and processes it through Docling's document model
to extract structured sections, figures, tables, and equations.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import httpx

from libs.adapters.ingestion.base import (
    IngestionError,
    IngestionResult,
    NormalizedEquation,
    NormalizedFigure,
    NormalizedSection,
    NormalizedTable,
    QualityAssessment,
)
from libs.core.logging import get_logger

log = get_logger("adapters.ingestion.pdf")


class PdfProcessor:
    """PDF ingestion adapter using Docling for extraction."""

    name: str = "pdf_docling"

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers or {"User-Agent": "Synthetos/0.1 (research-lab)"},
            follow_redirects=True,
        )

    async def fetch_fulltext(
        self,
        paper_url: str,
        pdf_url: str | None = None,
    ) -> IngestionResult:
        """Download PDF and extract structure via Docling."""
        t0 = time.monotonic()

        url = pdf_url or paper_url
        if not url:
            raise IngestionError("No PDF URL provided")

        log.info("fetching_pdf", url=url)
        resp = await self._client.get(url)
        resp.raise_for_status()
        pdf_bytes = resp.content

        # Write to temp file for Docling processing
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = Path(f.name)

        try:
            sections, figures, tables, equations, text = _process_with_docling(
                tmp_path,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        quality = _assess_quality(sections, figures, tables, equations)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return IngestionResult(
            content=text,
            normalized_sections=sections,
            normalized_figures=figures,
            normalized_tables=tables,
            normalized_equations=equations,
            fetch_method="pdf_docling",
            source_url=url,
            quality_assessment=quality,
            fetch_duration_ms=elapsed_ms,
        )

    async def close(self) -> None:
        await self._client.aclose()


def _process_with_docling(
    pdf_path: Path,
) -> tuple[
    list[NormalizedSection],
    list[NormalizedFigure],
    list[NormalizedTable],
    list[NormalizedEquation],
    str,
]:
    """Run Docling over a PDF and extract normalized structure.

    Imports docling lazily so the dependency is only required when
    the PDF fallback is actually used.
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise IngestionError(
            "docling is required for PDF processing but is not installed. "
            "Install with: uv add docling"
        ) from exc

    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    doc = result.document

    # Extract sections from the Docling document model
    sections: list[NormalizedSection] = []
    figures: list[NormalizedFigure] = []
    tables: list[NormalizedTable] = []
    equations: list[NormalizedEquation] = []

    # Walk document items
    for _i, item in enumerate(doc.iterate_items()):
        item_obj = item[1] if isinstance(item, tuple) else item
        label = getattr(item_obj, "label", None) or ""
        text = getattr(item_obj, "text", "") or ""
        label_str = str(label)

        if "heading" in label_str.lower() or "title" in label_str.lower():
            # Determine heading level from label
            level = 1
            if "section" in label_str.lower():
                level = 2
            sections.append(NormalizedSection(
                heading=text,
                level=level,
                content="",
            ))
        elif "paragraph" in label_str.lower() or "text" in label_str.lower():
            if sections:
                # Append to the last section's content
                last = sections[-1]
                content = last.content + "\n" + text if last.content else text
                sections[-1] = last.model_copy(update={"content": content})
            else:
                sections.append(NormalizedSection(
                    heading="Introduction",
                    level=1,
                    content=text,
                ))
        elif "figure" in label_str.lower():
            figures.append(NormalizedFigure(
                id=f"fig-{len(figures) + 1}",
                caption=text,
                content_description=text,
            ))
        elif "table" in label_str.lower():
            tables.append(NormalizedTable(
                id=f"table-{len(tables) + 1}",
                caption=text,
                content_description=text[:500] if text else "",
            ))
        elif "equation" in label_str.lower() or "formula" in label_str.lower():
            equations.append(NormalizedEquation(
                id=f"eq-{len(equations) + 1}",
                latex=text,
            ))

    # Build full text from sections
    full_text = "\n\n".join(
        f"## {s.heading}\n{s.content}" for s in sections if s.content
    )

    return sections, figures, tables, equations, full_text


def _assess_quality(
    sections: list[NormalizedSection],
    figures: list[NormalizedFigure],
    tables: list[NormalizedTable],
    equations: list[NormalizedEquation],
) -> QualityAssessment:
    """Compute quality assessment for PDF extraction."""
    warnings: list[str] = []

    if len(sections) < 2:
        warnings.append("Very few sections extracted from PDF")

    total_text = sum(len(s.content) for s in sections)
    if total_text < 500:
        warnings.append("Very little text extracted from PDF")

    score = 1.0
    if len(sections) < 3:
        score -= 0.3
    if total_text < 1000:
        score -= 0.2
    score = max(0.0, min(1.0, score))

    return QualityAssessment(
        structure_preserved=len(sections) >= 3 and total_text >= 1000,
        section_count=len(sections),
        figure_count=len(figures),
        table_count=len(tables),
        equation_count=len(equations),
        quality_score=score,
        quality_warnings=warnings,
    )
