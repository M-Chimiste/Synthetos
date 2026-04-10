"""Render the discovery report bundle (markdown + JSON).

A bundle is written to ``LAB_DATA_ROOT/artifacts/discovery/<session_id>/``
containing:
  * ``report.md`` -- human-readable report
  * ``report.json`` -- structured payload for orchestrators
  * ``papers.jsonl`` -- one row per included paper

Both formats stay deterministic given the same inputs so reports diff
cleanly between runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from libs.storage.models.discovery import DiscoverySession, ProblemProfile
    from libs.storage.models.papers import PaperCard


@dataclass
class ReportPaths:
    root: Path
    markdown: Path
    json: Path
    papers_jsonl: Path


def build_report_paths(data_root: Path, session_id) -> ReportPaths:
    root = data_root / "artifacts" / "discovery" / str(session_id)
    return ReportPaths(
        root=root,
        markdown=root / "report.md",
        json=root / "report.json",
        papers_jsonl=root / "papers.jsonl",
    )


def _truncate(text: str, n: int = 240) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def _format_card_md(card: PaperCard, idx: int) -> str:
    score = card.final_score or 0.0
    title = card.title or "(untitled)"
    venue = f" — {card.venue}" if card.venue else ""
    year = f" ({card.year})" if card.year else ""
    authors = ", ".join((card.authors or [])[:4])
    if card.authors and len(card.authors) > 4:
        authors += " et al."
    abstract = _truncate(card.abstract or "")
    analysis = card.metadata_analysis or {}
    summary = analysis.get("one_line_summary") or ""
    rationale = analysis.get("escalation_rationale") or ""
    pdf_link = f" [pdf]({card.pdf_url})" if card.pdf_url else ""
    src_link = f" [source]({card.source_url})" if card.source_url else ""

    parts = [
        f"### {idx}. {title}{year}{venue}",
        f"*{authors}* — score `{score:.4f}` — `{card.source}`{src_link}{pdf_link}",
    ]
    if summary:
        parts.append(f"> {summary}")
    if rationale:
        parts.append(f"_Why it matters:_ {rationale}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    return "\n\n".join(parts)


def render_markdown(
    *,
    session: DiscoverySession,
    profile: ProblemProfile,
    stable_view: list[PaperCard],
    discovery_view: list[PaperCard],
    stats: dict[str, Any],
) -> str:
    started = session.started_at.isoformat() if session.started_at else "—"
    completed = session.completed_at.isoformat() if session.completed_at else "—"
    lines: list[str] = [
        f"# Discovery report -- session `{session.id}`",
        "",
        f"- **Cycle:** `{session.cycle_id}`",
        f"- **Charter:** `{session.charter_id}`",
        f"- **Started:** {started}",
        f"- **Completed:** {completed}",
        f"- **View:** {session.view}",
        "",
        "## Problem statement",
        "",
        profile.query_text.strip(),
        "",
    ]
    if profile.notes:
        lines.extend(["**Notes:**", "", profile.notes.strip(), ""])

    lines.extend(
        [
            "## Stats",
            "",
            "```json",
            orjson.dumps(stats, option=orjson.OPT_INDENT_2).decode("utf-8"),
            "```",
            "",
        ]
    )

    critique = stats.get("shortlist_critique") if isinstance(stats, dict) else None
    if isinstance(critique, dict):
        lines.extend(
            [
                "## Shortlist critique",
                "",
                critique.get("summary") or "",
                "",
            ]
        )
        for label, key in (
            ("Coverage gaps", "coverage_gaps"),
            ("Clustering risks", "clustering_risks"),
            ("Score concerns", "score_concerns"),
        ):
            items = critique.get(key)
            if isinstance(items, list) and items:
                lines.append(f"**{label}:**")
                lines.append("")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")

    if stable_view:
        lines.append("## Stable view")
        lines.append("")
        for idx, card in enumerate(stable_view, start=1):
            lines.append(_format_card_md(card, idx))
            lines.append("")

    if discovery_view:
        lines.append("## Discovery view")
        lines.append("")
        for idx, card in enumerate(discovery_view, start=1):
            lines.append(_format_card_md(card, idx))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(
    *,
    session: DiscoverySession,
    profile: ProblemProfile,
    stable_view: list[PaperCard],
    discovery_view: list[PaperCard],
    stats: dict[str, Any],
) -> dict[str, Any]:
    def _card(card: PaperCard) -> dict[str, Any]:
        return {
            "id": str(card.id),
            "source": card.source,
            "external_id": card.external_id,
            "title": card.title,
            "authors": card.authors or [],
            "venue": card.venue,
            "year": card.year,
            "doi": card.doi,
            "source_url": card.source_url,
            "pdf_url": card.pdf_url,
            "first_stage_score": card.first_stage_score,
            "rerank_score": card.rerank_score,
            "final_score": card.final_score,
            "triage_status": card.triage_status,
            "metadata_analysis": card.metadata_analysis,
        }

    return {
        "session": {
            "id": str(session.id),
            "cycle_id": str(session.cycle_id),
            "charter_id": str(session.charter_id),
            "view": session.view,
            "status": session.status,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        "profile": {
            "id": str(profile.id),
            "query_text": profile.query_text,
            "notes": profile.notes,
            "view_preference": profile.view_preference,
            "rerank_policy": profile.rerank_policy,
            "budget": profile.budget,
            "source_scope": profile.source_scope,
        },
        "stats": stats,
        "stable_view": [_card(c) for c in stable_view],
        "discovery_view": [_card(c) for c in discovery_view],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def write_report_bundle(
    paths: ReportPaths,
    *,
    markdown: str,
    json_payload: dict[str, Any],
    cards: list[PaperCard],
) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.markdown.write_text(markdown, encoding="utf-8")
    paths.json.write_bytes(orjson.dumps(json_payload, option=orjson.OPT_INDENT_2))
    with paths.papers_jsonl.open("wb") as f:
        for card in cards:
            row = {
                "id": str(card.id),
                "source": card.source,
                "external_id": card.external_id,
                "title": card.title,
                "abstract": card.abstract,
                "authors": card.authors or [],
                "venue": card.venue,
                "year": card.year,
                "doi": card.doi,
                "source_url": card.source_url,
                "pdf_url": card.pdf_url,
                "first_stage_score": card.first_stage_score,
                "rerank_score": card.rerank_score,
                "final_score": card.final_score,
                "view_membership": card.view_membership or [],
                "triage_status": card.triage_status,
                "metadata_analysis": card.metadata_analysis,
            }
            f.write(orjson.dumps(row))
            f.write(b"\n")
