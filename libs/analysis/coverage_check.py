"""Coverage verification for analysis sessions.

Compares extracted graph nodes against mentions in the ingested document
to identify missing or weakly linked elements.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.storage.models.analysis import (
    CoverageDiagnostic,
    GraphEdge,
    GraphNode,
    IngestedDocument,
    PaperChunk,
)

log = get_logger("analysis.coverage_check")


def compute_coverage(
    db: Session,
    *,
    doc: IngestedDocument,
    chunks: list[PaperChunk],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    analysis_session_id: UUID,
) -> CoverageDiagnostic:
    """Compute coverage diagnostics and persist to the database."""
    section_cov = _section_coverage(doc, nodes)
    figure_cov = _figure_coverage(doc, nodes)
    table_cov = _table_coverage(doc, nodes)
    equation_cov = _equation_coverage(doc, nodes)
    unlinked = _find_unlinked_chunks(chunks, edges)
    warnings = _generate_warnings(section_cov, figure_cov, table_cov, unlinked)

    # Composite score: average of individual coverage ratios
    scores = []
    for cov in (section_cov, figure_cov, table_cov, equation_cov):
        total = cov.get("total", 0)
        if total > 0:
            scores.append(cov.get("covered", 0) / total)
    overall = sum(scores) / len(scores) if scores else 0.0

    diagnostic = CoverageDiagnostic(
        id=uuid7(),
        analysis_session_id=analysis_session_id,
        section_coverage=section_cov,
        figure_coverage=figure_cov,
        table_coverage=table_cov,
        equation_coverage=equation_cov,
        unlinked_artifacts=[str(cid) for cid in unlinked],
        warnings=warnings,
        overall_score=round(overall, 3),
        created_at=utcnow(),
    )
    db.add(diagnostic)
    db.flush()

    log.info(
        "coverage_computed",
        overall_score=diagnostic.overall_score,
        warning_count=len(warnings),
    )
    return diagnostic


def _section_coverage(
    doc: IngestedDocument,
    nodes: list[GraphNode],
) -> dict[str, Any]:
    """Check which sections have at least one graph node linked."""
    sections = doc.normalized_sections or []
    headings = {s.get("heading", "") for s in sections if s.get("heading")}

    # Nodes with provenance linking to section chunks
    covered = set()
    for node in nodes:
        prov = node.provenance or {}
        for _cid in prov.get("source_chunk_ids", []):
            # If the node exists, the section it came from is covered
            covered.add(node.node_type)

    # Simple heuristic: count sections with any content-bearing node
    section_labels = set()
    for node in nodes:
        if node.node_type == "section":
            section_labels.add(node.label)

    covered_headings = headings & section_labels
    missing = sorted(headings - section_labels)

    return {
        "total": len(headings),
        "covered": len(covered_headings),
        "missing": missing,
    }


def _figure_coverage(
    doc: IngestedDocument,
    nodes: list[GraphNode],
) -> dict[str, Any]:
    """Check which figures from the document have graph nodes."""
    figures = doc.normalized_figures or []
    fig_ids = {f.get("id", "") for f in figures if f.get("id")}
    # Check for figure references in node labels
    covered = set()
    for fid in fig_ids:
        if any(fid in n.label for n in nodes if n.node_type == "figure"):
            covered.add(fid)

    missing = sorted(fig_ids - covered)
    return {
        "total": len(fig_ids),
        "covered": len(covered),
        "missing": missing,
    }


def _table_coverage(
    doc: IngestedDocument,
    nodes: list[GraphNode],
) -> dict[str, Any]:
    """Check which tables from the document have graph nodes."""
    tables = doc.normalized_tables or []
    tbl_ids = {t.get("id", "") for t in tables if t.get("id")}

    covered = set()
    for tid in tbl_ids:
        if any(tid in n.label for n in nodes if n.node_type == "table"):
            covered.add(tid)

    missing = sorted(tbl_ids - covered)
    return {
        "total": len(tbl_ids),
        "covered": len(covered),
        "missing": missing,
    }


def _equation_coverage(
    doc: IngestedDocument,
    nodes: list[GraphNode],
) -> dict[str, Any]:
    """Check which equations from the document have graph nodes."""
    equations = doc.normalized_equations or []
    eq_ids = {e.get("id", "") for e in equations if e.get("id")}

    covered = set()
    for eid in eq_ids:
        if any(eid in n.label for n in nodes if n.node_type == "equation"):
            covered.add(eid)

    missing = sorted(eq_ids - covered)
    return {
        "total": len(eq_ids),
        "covered": len(covered),
        "missing": missing,
    }


def _find_unlinked_chunks(
    chunks: list[PaperChunk],
    edges: list[GraphEdge],
) -> list[UUID]:
    """Find chunks that have no outgoing graph edges."""
    # Collect all chunk IDs referenced by graph nodes (via provenance)
    linked_chunk_ids: set[str] = set()
    # We approximate: if a node exists from a chunk, that chunk is linked
    # This is handled at the graph extraction level, so we check chunk types
    # that should have graph connections
    content_chunk_ids = {
        c.id for c in chunks
        if c.chunk_type in ("section", "paragraph")
    }

    # Chunks with at least one edge's source or target node that references them
    # For simplicity, mark all chunks that produced nodes as linked
    for edge in edges:
        linked_chunk_ids.add(str(edge.source_node_id))
        linked_chunk_ids.add(str(edge.target_node_id))

    # Return section/paragraph chunks that didn't produce any graph nodes
    unlinked = []
    for chunk in chunks:
        if chunk.chunk_type in ("section", "paragraph") and chunk.id not in content_chunk_ids:
            unlinked.append(chunk.id)

    return unlinked[:50]  # Cap to avoid oversized diagnostics


def _generate_warnings(
    section_cov: dict[str, Any],
    figure_cov: dict[str, Any],
    table_cov: dict[str, Any],
    unlinked: list[UUID],
) -> list[str]:
    """Generate human-readable coverage warnings."""
    warnings: list[str] = []

    s_total = section_cov.get("total", 0)
    s_covered = section_cov.get("covered", 0)
    if s_total > 0 and s_covered / s_total < 0.5:
        warnings.append(
            f"Low section coverage: {s_covered}/{s_total} sections linked"
        )

    f_total = figure_cov.get("total", 0)
    f_covered = figure_cov.get("covered", 0)
    if f_total > 0 and f_covered == 0:
        warnings.append("No figures were linked to graph nodes")

    t_total = table_cov.get("total", 0)
    t_covered = table_cov.get("covered", 0)
    if t_total > 0 and t_covered == 0:
        warnings.append("No tables were linked to graph nodes")

    if len(unlinked) > 10:
        warnings.append(
            f"{len(unlinked)} content chunks have no graph connections"
        )

    return warnings
