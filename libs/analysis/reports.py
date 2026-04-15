"""Render the analysis report bundle (markdown + JSON)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from libs.storage.models.analysis import (
        AnalysisSession,
        CoverageDiagnostic,
        EvidenceCard,
        PaperAnalysisPacket,
        PaperReviewArtifact,
    )


@dataclass
class ReportPaths:
    root: Path
    markdown: Path
    json: Path


def build_report_paths(data_root: Path, session_id) -> ReportPaths:
    root = data_root / "artifacts" / "analysis" / str(session_id)
    return ReportPaths(
        root=root,
        markdown=root / "report.md",
        json=root / "report.json",
    )


def render_markdown(
    *,
    session: AnalysisSession,
    packet: PaperAnalysisPacket,
    review: PaperReviewArtifact,
    coverage: CoverageDiagnostic | None,
    evidence_cards: list[EvidenceCard] | None = None,
) -> str:
    started = session.started_at.isoformat() if session.started_at else "—"
    completed = session.completed_at.isoformat() if session.completed_at else "—"
    lines: list[str] = [
        f"# Analysis report -- session `{session.id}`",
        "",
        f"- **Paper:** `{session.paper_card_id}`",
        f"- **Cycle:** `{session.cycle_id}`",
        f"- **Charter:** `{session.charter_id}`",
        f"- **Started:** {started}",
        f"- **Completed:** {completed}",
        f"- **Status:** {session.status}",
        "",
        "## Summary",
        "",
        packet.summary,
        "",
    ]

    if packet.key_contributions:
        lines.extend(["## Key contributions", ""])
        lines.extend(f"- {item}" for item in packet.key_contributions)
        lines.append("")

    if packet.methods_used:
        lines.extend(["## Methods", ""])
        for item in packet.methods_used:
            name = item.get("name") or "(unnamed)"
            desc = item.get("description") or ""
            lines.append(f"- {name}: {desc}".rstrip(": "))
        lines.append("")

    if coverage:
        lines.extend(
            [
                "## Coverage",
                "",
                f"- **Overall score:** {coverage.overall_score:.2f}",
            ]
        )
        if coverage.warnings:
            lines.append("- **Warnings:**")
            lines.extend(f"  - {warning}" for warning in coverage.warnings)
        lines.append("")

    lines.extend(["## Review", ""])
    if review.strengths:
        lines.append("**Strengths**")
        lines.extend(f"- {item}" for item in review.strengths)
        lines.append("")
    if review.weaknesses:
        lines.append("**Weaknesses**")
        lines.extend(f"- {item}" for item in review.weaknesses)
        lines.append("")
    if review.open_questions:
        lines.append("**Open questions**")
        lines.extend(f"- {item}" for item in review.open_questions)
        lines.append("")
    if review.critique:
        lines.extend(["**Critique**", "", review.critique, ""])
    if review.scores:
        lines.extend(["**Scores**", ""])
        for key, value in review.scores.items():
            lines.append(f"- {key}: {value:.2f}")
        lines.append("")

    if evidence_cards:
        lines.extend(["## Evidence highlights", ""])
        for card in evidence_cards[:10]:
            lines.append(f"- [{card.evidence_type}] {card.claim}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(
    *,
    session: AnalysisSession,
    packet: PaperAnalysisPacket,
    review: PaperReviewArtifact,
    coverage: CoverageDiagnostic | None,
    evidence_cards: list[EvidenceCard] | None = None,
) -> dict[str, Any]:
    return {
        "session": {
            "id": str(session.id),
            "paper_card_id": str(session.paper_card_id),
            "cycle_id": str(session.cycle_id),
            "charter_id": str(session.charter_id),
            "status": session.status,
            "budget": session.budget,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        "packet": {
            "id": str(packet.id),
            "summary": packet.summary,
            "key_contributions": packet.key_contributions,
            "methods_used": packet.methods_used,
            "datasets_referenced": packet.datasets_referenced,
            "reproducibility_notes": packet.reproducibility_notes,
            "graph_summary": packet.graph_summary,
            "coverage_snapshot": packet.coverage_snapshot,
            "chunk_count": packet.chunk_count,
            "node_count": packet.node_count,
            "edge_count": packet.edge_count,
        },
        "review": {
            "id": str(review.id),
            "strengths": review.strengths,
            "weaknesses": review.weaknesses,
            "open_questions": review.open_questions,
            "critique": review.critique,
            "scores": review.scores,
            "reading_priority": review.reading_priority,
        },
        "coverage": {
            "overall_score": coverage.overall_score,
            "section_coverage": coverage.section_coverage,
            "figure_coverage": coverage.figure_coverage,
            "table_coverage": coverage.table_coverage,
            "equation_coverage": coverage.equation_coverage,
            "warnings": coverage.warnings,
        }
        if coverage
        else None,
        "evidence_cards": [
            {
                "id": str(card.id),
                "evidence_type": card.evidence_type,
                "claim": card.claim,
                "supporting_text": card.supporting_text,
                "confidence": card.confidence,
                "contradiction_flags": card.contradiction_flags,
                "redundancy_group": card.redundancy_group,
            }
            for card in (evidence_cards or [])
        ],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def write_report_bundle(
    paths: ReportPaths,
    *,
    markdown: str,
    json_payload: dict[str, Any],
) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.markdown.write_text(markdown, encoding="utf-8")
    paths.json.write_bytes(orjson.dumps(json_payload, option=orjson.OPT_INDENT_2))
