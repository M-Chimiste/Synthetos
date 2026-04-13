"""HTML-first paper ingestion adapter.

Fetches full-text HTML (ar5iv for arXiv papers, direct endpoints for others),
parses structure with BeautifulSoup, and returns normalized sections, figures,
tables, and equations with a quality assessment.
"""

from __future__ import annotations

import re
import time

import httpx
from bs4 import BeautifulSoup, Tag

from libs.adapters.ingestion.base import (
    IngestionResult,
    NormalizedEquation,
    NormalizedFigure,
    NormalizedSection,
    NormalizedTable,
    QualityAssessment,
)
from libs.core.logging import get_logger

log = get_logger("adapters.ingestion.html")

# ar5iv converts arXiv PDFs to semantic HTML
_AR5IV_BASE = "https://ar5iv.labs.arxiv.org/html/"

# Headings that delimit sections
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _arxiv_id_from_url(url: str) -> str | None:
    """Extract an arXiv ID from common URL formats."""
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url)
    return m.group(1) if m else None


def _build_ar5iv_url(paper_url: str) -> str | None:
    """Convert an arXiv URL to its ar5iv HTML equivalent."""
    arxiv_id = _arxiv_id_from_url(paper_url)
    if arxiv_id:
        return f"{_AR5IV_BASE}{arxiv_id}"
    return None


def _heading_level(tag: Tag) -> int:
    name = tag.name or ""
    if name in _HEADING_TAGS:
        return int(name[1])
    return 0


def _extract_sections(soup: BeautifulSoup) -> list[NormalizedSection]:
    """Walk the document and split by headings into sections."""
    sections: list[NormalizedSection] = []
    current_heading = "Abstract"
    current_level = 1
    current_parts: list[str] = []

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"]):
        if element.name in _HEADING_TAGS:
            # Flush previous section
            text = "\n".join(current_parts).strip()
            if text:
                sections.append(NormalizedSection(
                    heading=current_heading,
                    level=current_level,
                    content=text,
                ))
            current_heading = element.get_text(strip=True)
            current_level = _heading_level(element)
            current_parts = []
        else:
            t = element.get_text(strip=True)
            if t:
                current_parts.append(t)

    # Flush last section
    text = "\n".join(current_parts).strip()
    if text:
        sections.append(NormalizedSection(
            heading=current_heading,
            level=current_level,
            content=text,
        ))

    return sections


def _extract_figures(soup: BeautifulSoup) -> list[NormalizedFigure]:
    """Extract figure captions from <figure> and <figcaption> elements."""
    figures: list[NormalizedFigure] = []
    for i, fig in enumerate(soup.find_all("figure"), start=1):
        caption_el = fig.find("figcaption")
        caption = caption_el.get_text(strip=True) if caption_el else ""
        fig_id = fig.get("id", f"fig-{i}")
        figures.append(NormalizedFigure(
            id=str(fig_id),
            caption=caption,
            content_description=caption,
        ))
    return figures


def _extract_tables(soup: BeautifulSoup) -> list[NormalizedTable]:
    """Extract tables with their captions."""
    tables: list[NormalizedTable] = []
    for i, tbl in enumerate(soup.find_all("table"), start=1):
        # Look for a caption element
        caption_el = tbl.find("caption")
        caption = caption_el.get_text(strip=True) if caption_el else ""
        tbl_id = tbl.get("id", f"table-{i}")
        # Flatten table content as a rough text description
        content = tbl.get_text(separator=" | ", strip=True)[:500]
        tables.append(NormalizedTable(
            id=str(tbl_id),
            caption=caption,
            content_description=content,
        ))
    return tables


def _extract_equations(soup: BeautifulSoup) -> list[NormalizedEquation]:
    """Extract LaTeX equations from math elements."""
    equations: list[NormalizedEquation] = []
    for i, math_el in enumerate(
        soup.find_all(["math", "span"], class_=re.compile(r"math|equation", re.I)),
        start=1,
    ):
        raw_latex = math_el.get("alttext", "") or math_el.get_text(strip=True)
        latex = raw_latex if isinstance(raw_latex, str) else str(raw_latex)
        if latex:
            eq_id = math_el.get("id", f"eq-{i}")
            equations.append(NormalizedEquation(
                id=str(eq_id),
                latex=latex,
            ))
    return equations


def _assess_quality(
    sections: list[NormalizedSection],
    figures: list[NormalizedFigure],
    tables: list[NormalizedTable],
    equations: list[NormalizedEquation],
) -> QualityAssessment:
    """Compute a quality score for the extracted structure."""
    warnings: list[str] = []

    if len(sections) < 2:
        warnings.append("Very few sections extracted; document may lack structure")
    if not any(s.level > 1 for s in sections):
        warnings.append("No sub-headings found; heading hierarchy may be missing")

    total_text = sum(len(s.content) for s in sections)
    if total_text < 500:
        warnings.append("Very little text extracted")

    # Score: penalize for missing structure
    score = 1.0
    if len(sections) < 3:
        score -= 0.3
    if total_text < 1000:
        score -= 0.2
    if not figures and not tables:
        score -= 0.1
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


class HtmlFetcher:
    """HTML-first paper ingestion adapter."""

    name: str = "html"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
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
        """Fetch HTML, parse structure, and return normalized result."""
        t0 = time.monotonic()

        # Try ar5iv first for arXiv papers
        fetch_url = _build_ar5iv_url(paper_url) or paper_url
        log.info("fetching_html", url=fetch_url)

        resp = await self._client.get(fetch_url)
        resp.raise_for_status()
        html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        sections = _extract_sections(soup)
        figures = _extract_figures(soup)
        tables = _extract_tables(soup)
        equations = _extract_equations(soup)
        quality = _assess_quality(sections, figures, tables, equations)

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return IngestionResult(
            content=html,
            normalized_sections=sections,
            normalized_figures=figures,
            normalized_tables=tables,
            normalized_equations=equations,
            fetch_method="html",
            source_url=fetch_url,
            quality_assessment=quality,
            fetch_duration_ms=elapsed_ms,
        )

    async def close(self) -> None:
        await self._client.aclose()
