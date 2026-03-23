"""Literature triage business logic.

Handles paper ingestion, deduplication, screening, shortlisting,
escalation recording, and report generation.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.adapters.literature import RawPaperRecord
from libs.core.ids import generate_public_id
from libs.schemas.api import (
    LiteratureTriageResponse,
    PaperCardSummary,
)
from libs.schemas.domain import SourceRetrievalSession
from libs.storage.models import (
    PaperCardModel,
    ResearchCycleModel,
    ScreeningDecisionModel,
    SourceRetrievalSessionModel,
)

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _extract_arxiv_id(raw: RawPaperRecord) -> str | None:
    if raw.source_type == "arxiv" and raw.external_id:
        return raw.external_id.strip().lower()
    if raw.metadata_extra.get("arxiv_id"):
        return str(raw.metadata_extra["arxiv_id"]).strip().lower()
    if raw.source_url and "arxiv.org/abs/" in raw.source_url:
        return raw.source_url.rsplit("/", 1)[-1].strip().lower()
    return None


def _extract_year(raw: RawPaperRecord) -> str:
    if raw.publication_date and len(raw.publication_date) >= 4:
        return raw.publication_date[:4]
    updated = raw.metadata_extra.get("updated")
    if isinstance(updated, str) and len(updated) >= 4:
        return updated[:4]
    return "unknown"


def _content_hash(raw: RawPaperRecord) -> str:
    return _identity_aliases(raw)[0]


def _identity_aliases(raw: RawPaperRecord) -> list[str]:
    aliases: list[str] = []
    arxiv_id = _extract_arxiv_id(raw)
    if arxiv_id:
        aliases.append(f"arxiv:{arxiv_id}")

    doi = raw.metadata_extra.get("doi")
    if isinstance(doi, str) and doi.strip():
        aliases.append(f"doi:{doi.strip().lower()}")

    title = _normalize_text(raw.title)
    year = _extract_year(raw)
    digest = hashlib.sha256(f"{title}|{year}".encode()).hexdigest()
    aliases.append(f"title:{digest}")
    return aliases


def _retrieval_provenance_entry(
    retrieval_session: SourceRetrievalSessionModel,
    raw: RawPaperRecord,
) -> dict[str, Any]:
    return {
        "source_type": raw.source_type,
        "retrieval_session_public_id": retrieval_session.public_id,
        "external_id": raw.external_id,
        "source_url": raw.source_url,
        "pdf_url": raw.pdf_url,
    }


def retrieval_provenance_summary(metadata_extra: dict[str, Any]) -> list[str]:
    entries = metadata_extra.get("retrieval_provenance", [])
    if not isinstance(entries, list):
        return []
    summary: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_type = str(entry.get("source_type", "unknown"))
        external_id = str(entry.get("external_id", "unknown"))
        summary.append(f"{source_type}: {external_id}")
    return summary


def _merge_paper_metadata(
    paper: PaperCardModel,
    retrieval_session: SourceRetrievalSessionModel,
    raw: RawPaperRecord,
    canonical_key: str,
) -> None:
    metadata_extra = dict(paper.metadata_extra or {})
    metadata_extra.setdefault("canonical_identity", canonical_key)
    aliases = metadata_extra.get("identity_aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    metadata_extra["identity_aliases"] = sorted(
        {*aliases, *_identity_aliases(raw), paper.content_hash or canonical_key}
    )

    provenance = metadata_extra.get("retrieval_provenance", [])
    if not isinstance(provenance, list):
        provenance = []
    entry = _retrieval_provenance_entry(retrieval_session, raw)
    if entry not in provenance:
        provenance.append(entry)
    metadata_extra["retrieval_provenance"] = provenance

    for key, value in raw.metadata_extra.items():
        metadata_extra.setdefault(key, value)
    paper.metadata_extra = metadata_extra

    if not paper.abstract and raw.abstract:
        paper.abstract = raw.abstract
    if not paper.authors and raw.authors:
        paper.authors = raw.authors
    if raw.categories:
        paper.categories = sorted({*paper.categories, *raw.categories})
    if paper.publication_date is None and raw.publication_date:
        try:
            paper.publication_date = datetime.fromisoformat(
                raw.publication_date
            ).replace(tzinfo=UTC)
        except ValueError:
            pass
    if not paper.source_url and raw.source_url:
        paper.source_url = raw.source_url
    if not paper.pdf_url and raw.pdf_url:
        paper.pdf_url = raw.pdf_url

    if _identity_priority(canonical_key) < _identity_priority(paper.content_hash or ""):
        paper.content_hash = canonical_key
        metadata_extra["canonical_identity"] = canonical_key
        paper.metadata_extra = metadata_extra


def _identity_priority(identity: str) -> int:
    if identity.startswith("arxiv:"):
        return 0
    if identity.startswith("doi:"):
        return 1
    return 2


def _paper_year(paper: PaperCardModel) -> str:
    if paper.publication_date is not None:
        return str(paper.publication_date.year)
    updated = (paper.metadata_extra or {}).get("updated")
    if isinstance(updated, str) and len(updated) >= 4:
        return updated[:4]
    return "unknown"


def _find_existing_paper(
    session: Session,
    cycle_id: int,
    identities: list[str],
    raw: RawPaperRecord,
) -> PaperCardModel | None:
    direct = session.scalar(
        select(PaperCardModel).where(
            PaperCardModel.cycle_id == cycle_id,
            PaperCardModel.content_hash.in_(identities),
        )
    )
    if direct is not None:
        return direct

    normalized_title = _normalize_text(raw.title)
    year = _extract_year(raw)
    candidates = session.scalars(
        select(PaperCardModel).where(PaperCardModel.cycle_id == cycle_id)
    ).all()
    for candidate in candidates:
        metadata_extra = candidate.metadata_extra or {}
        aliases = metadata_extra.get("identity_aliases", [])
        if isinstance(aliases, list) and set(aliases).intersection(identities):
            return candidate
        if _normalize_text(candidate.title) == normalized_title and _paper_year(candidate) == year:
            return candidate
    return None


def ingest_papers(
    session: Session,
    cycle: ResearchCycleModel,
    retrieval_session: SourceRetrievalSessionModel,
    raw_papers: list[RawPaperRecord],
) -> list[PaperCardModel]:
    """Deduplicate and persist paper cards from a retrieval session."""
    created: list[PaperCardModel] = []
    retrieval_count = 0
    for raw in raw_papers:
        retrieval_count += 1
        aliases = _identity_aliases(raw)
        chash = aliases[0]
        existing = _find_existing_paper(session, cycle.id, aliases, raw)
        if existing is not None:
            _merge_paper_metadata(existing, retrieval_session, raw, chash)
            continue

        pub_date = None
        if raw.publication_date:
            try:
                pub_date = datetime.fromisoformat(raw.publication_date).replace(tzinfo=UTC)
            except ValueError:
                pass

        paper = PaperCardModel(
            public_id=generate_public_id("paper"),
            cycle_id=cycle.id,
            retrieval_session_id=retrieval_session.id,
            source_type=raw.source_type,
            external_id=raw.external_id,
            title=raw.title,
            abstract=raw.abstract,
            authors=raw.authors,
            categories=raw.categories,
            publication_date=pub_date,
            source_url=raw.source_url,
            pdf_url=raw.pdf_url,
            metadata_extra={
                **raw.metadata_extra,
                "canonical_identity": chash,
                "identity_aliases": aliases,
                "retrieval_provenance": [
                    _retrieval_provenance_entry(retrieval_session, raw),
                ],
            },
            lifecycle_status="retrieved",
            content_hash=chash,
        )
        session.add(paper)
        created.append(paper)

    session.flush()
    retrieval_session.result_count = retrieval_count
    retrieval_session.status = "completed"
    session.flush()
    return created


def ingest_raw_records(
    session: Session,
    cycle: ResearchCycleModel,
    retrieval_session: SourceRetrievalSessionModel,
    raw_records: list[RawPaperRecord],
) -> list[PaperCardModel]:
    """Alias used by retrieval adapters that already return RawPaperRecord objects."""
    return ingest_papers(session, cycle, retrieval_session, raw_records)


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

def get_papers_for_screening(
    session: Session, cycle_id: int, batch_size: int = 20,
) -> list[PaperCardModel]:
    """Get next batch of papers in 'retrieved' status for triage."""
    return list(
        session.scalars(
            select(PaperCardModel)
            .where(
                PaperCardModel.cycle_id == cycle_id,
                PaperCardModel.lifecycle_status == "retrieved",
            )
            .order_by(PaperCardModel.created_at.asc())
            .limit(batch_size)
        ).all()
    )


def record_screening_decision(
    session: Session,
    paper: PaperCardModel,
    decision: str,
    score: float,
    rationale: str,
    model_route_id: str,
    prompt_id: str,
    batch_index: int,
) -> ScreeningDecisionModel:
    """Record a triage decision and update paper lifecycle."""
    sd = ScreeningDecisionModel(
        public_id=generate_public_id("screen"),
        cycle_id=paper.cycle_id,
        paper_card_id=paper.id,
        decision=decision,
        score=score,
        rationale=rationale,
        model_route_id=model_route_id,
        prompt_id=prompt_id,
        batch_index=batch_index,
    )
    session.add(sd)
    paper.triage_score = score
    paper.triage_rationale = rationale
    paper.triage_model_route = model_route_id
    if decision == "reject":
        paper.lifecycle_status = "rejected"
    else:
        paper.lifecycle_status = "screened"
    session.flush()
    return sd


# ---------------------------------------------------------------------------
# Shortlisting
# ---------------------------------------------------------------------------

def compute_shortlist(
    session: Session, cycle_id: int, max_shortlist: int = 20,
) -> list[PaperCardModel]:
    """Rank screened papers by triage score and assign shortlist positions."""
    papers = list(
        session.scalars(
            select(PaperCardModel)
            .where(
                PaperCardModel.cycle_id == cycle_id,
                PaperCardModel.lifecycle_status == "screened",
                PaperCardModel.triage_score.isnot(None),
            )
            .order_by(PaperCardModel.triage_score.desc())
            .limit(max_shortlist)
        ).all()
    )
    for rank, paper in enumerate(papers, start=1):
        paper.shortlist_rank = rank
        paper.shortlist_reason = (
            f"Selected for shortlist at rank #{rank} based on triage score "
            f"{paper.triage_score:.2f} and metadata relevance."
        )
        paper.lifecycle_status = "shortlisted"
    session.flush()
    return papers


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

def get_escalation_candidates(
    session: Session, cycle_id: int,
) -> list[PaperCardModel]:
    """Shortlisted papers that haven't been fetched for deeper reading."""
    return list(
        session.scalars(
            select(PaperCardModel)
            .where(
                PaperCardModel.cycle_id == cycle_id,
                PaperCardModel.lifecycle_status == "shortlisted",
                PaperCardModel.fulltext_artifact_path.is_(None),
            )
            .order_by(PaperCardModel.shortlist_rank.asc(), PaperCardModel.created_at.asc())
        ).all()
    )


def select_escalation_candidates(
    session: Session,
    cycle_id: int,
    max_fetches: int,
) -> tuple[list[PaperCardModel], int]:
    candidates = get_escalation_candidates(session, cycle_id)
    if max_fetches <= 0:
        return [], len(candidates)
    selected = candidates[:max_fetches]
    skipped = max(len(candidates) - len(selected), 0)
    return selected, skipped


def build_escalation_reason(paper: PaperCardModel) -> str:
    score = paper.triage_score if paper.triage_score is not None else 0.0
    return (
        f"Escalated for deeper read because it is shortlisted at rank #{paper.shortlist_rank} "
        f"with triage score {score:.2f}; metadata suggests the full text may materially affect "
        "evidence synthesis."
    )


def record_escalation(
    session: Session,
    paper: PaperCardModel,
    content_type: str,
    artifact_path: str,
    reason: str,
) -> None:
    """Record that a paper's full text has been fetched."""
    paper.escalation_type = content_type
    paper.fulltext_artifact_path = artifact_path
    paper.escalation_reason = reason
    paper.lifecycle_status = f"{content_type}_fetched"
    session.flush()


# ---------------------------------------------------------------------------
# Summaries and Reports
# ---------------------------------------------------------------------------

def build_literature_triage_summary(
    session: Session, cycle: ResearchCycleModel,
) -> LiteratureTriageResponse:
    """Build the triage summary response for API/UI."""
    sessions = session.scalars(
        select(SourceRetrievalSessionModel)
        .where(SourceRetrievalSessionModel.cycle_id == cycle.id)
        .order_by(SourceRetrievalSessionModel.created_at.asc())
    ).all()

    total = session.scalar(
        select(func.count(PaperCardModel.id))
        .where(PaperCardModel.cycle_id == cycle.id)
    ) or 0
    screened = session.scalar(
        select(func.count(PaperCardModel.id))
        .where(
            PaperCardModel.cycle_id == cycle.id,
            PaperCardModel.lifecycle_status.notin_(["retrieved"]),
        )
    ) or 0
    shortlisted = session.scalar(
        select(func.count(PaperCardModel.id))
        .where(
            PaperCardModel.cycle_id == cycle.id,
            PaperCardModel.shortlist_rank.isnot(None),
        )
    ) or 0
    escalated = session.scalar(
        select(func.count(PaperCardModel.id))
        .where(
            PaperCardModel.cycle_id == cycle.id,
            PaperCardModel.fulltext_artifact_path.isnot(None),
        )
    ) or 0

    papers = session.scalars(
        select(PaperCardModel)
        .where(PaperCardModel.cycle_id == cycle.id)
        .order_by(
            PaperCardModel.shortlist_rank.asc().nullslast(),
            PaperCardModel.triage_score.desc().nullslast(),
            PaperCardModel.created_at.asc(),
        )
        .limit(100)
    ).all()

    return LiteratureTriageResponse(
        retrieval_sessions=[
            SourceRetrievalSession.model_validate(s) for s in sessions
        ],
        total_papers=total,
        screened_count=screened,
        shortlisted_count=shortlisted,
        escalated_count=escalated,
        papers=[
            PaperCardSummary(
                public_id=p.public_id,
                title=p.title,
                source_type=p.source_type,
                external_id=p.external_id,
                lifecycle_status=p.lifecycle_status,
                triage_score=p.triage_score,
                triage_rationale=p.triage_rationale,
                shortlist_rank=p.shortlist_rank,
                shortlist_reason=p.shortlist_reason,
                escalation_reason=p.escalation_reason,
                escalation_type=p.escalation_type,
                retrieval_provenance_summary=retrieval_provenance_summary(p.metadata_extra or {}),
                created_at=p.created_at,
            )
            for p in papers
        ],
    )


def build_screening_report_markdown(
    session: Session, cycle: ResearchCycleModel, charter_title: str,
) -> str:
    """Generate the literature screening packet as markdown."""
    summary = build_literature_triage_summary(session, cycle)

    lines = [
        f"# Literature Screening Report: {charter_title}",
        "",
        "## Summary",
        "",
        f"- Total papers retrieved: **{summary.total_papers}**",
        f"- Papers screened: **{summary.screened_count}**",
        f"- Papers shortlisted: **{summary.shortlisted_count}**",
        f"- Papers with full text: **{summary.escalated_count}**",
        "",
        "## Retrieval Sessions",
        "",
    ]

    for s in summary.retrieval_sessions:
        lines.append(
            f"- **{s.source_type}** — {s.result_count} results ({s.status})"
        )

    lines.extend(["", "## Shortlisted Papers", ""])

    shortlisted = session.scalars(
        select(PaperCardModel)
        .where(
            PaperCardModel.cycle_id == cycle.id,
            PaperCardModel.shortlist_rank.isnot(None),
        )
        .order_by(PaperCardModel.shortlist_rank.asc())
    ).all()

    for paper in shortlisted:
        score = f"{paper.triage_score:.2f}" if paper.triage_score is not None else "N/A"
        provenance = retrieval_provenance_summary(paper.metadata_extra or {})
        lines.extend([
            f"### #{paper.shortlist_rank}: {paper.title}",
            "",
            f"- **Source:** {paper.source_type} ({paper.external_id})",
            f"- **Provenance:** {', '.join(provenance) if provenance else 'N/A'}",
            f"- **Score:** {score}",
            f"- **Rationale:** {paper.triage_rationale or 'N/A'}",
            f"- **Shortlist reason:** {paper.shortlist_reason or 'N/A'}",
        ])
        if paper.escalation_type:
            lines.append(
                f"- **Escalated:** {paper.escalation_type} — {paper.escalation_reason or 'N/A'}"
            )
        lines.append("")

    # Rejected summary
    rejected_count = session.scalar(
        select(func.count(PaperCardModel.id))
        .where(
            PaperCardModel.cycle_id == cycle.id,
            PaperCardModel.lifecycle_status == "rejected",
        )
    ) or 0

    lines.extend([
        "## Rejected Papers",
        "",
        f"{rejected_count} papers were rejected during screening.",
        "",
    ])

    return "\n".join(lines)
