"""Literature triage business logic.

Handles paper ingestion, deduplication, screening, shortlisting,
escalation recording, and report generation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

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

def _content_hash(source_type: str, external_id: str) -> str:
    return hashlib.sha256(f"{source_type}:{external_id}".encode()).hexdigest()


def ingest_papers(
    session: Session,
    cycle: ResearchCycleModel,
    retrieval_session: SourceRetrievalSessionModel,
    raw_papers: list[RawPaperRecord],
) -> list[PaperCardModel]:
    """Deduplicate and persist paper cards from a retrieval session."""
    created: list[PaperCardModel] = []
    for raw in raw_papers:
        chash = _content_hash(raw.source_type, raw.external_id)
        existing = session.scalar(
            select(PaperCardModel).where(
                PaperCardModel.cycle_id == cycle.id,
                PaperCardModel.content_hash == chash,
            )
        )
        if existing is not None:
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
            metadata_extra=raw.metadata_extra,
            lifecycle_status="retrieved",
            content_hash=chash,
        )
        session.add(paper)
        created.append(paper)

    session.flush()
    retrieval_session.result_count = len(created)
    retrieval_session.status = "completed"
    session.flush()
    return created


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
            f"Ranked #{rank} by triage score {paper.triage_score:.2f}"
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
            .order_by(PaperCardModel.shortlist_rank.asc())
        ).all()
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
                shortlist_rank=p.shortlist_rank,
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
        lines.extend([
            f"### #{paper.shortlist_rank}: {paper.title}",
            "",
            f"- **Source:** {paper.source_type} ({paper.external_id})",
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
