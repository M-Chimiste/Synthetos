"""LLM-driven evidence extraction from paper analysis packets.

Produces ``EvidenceCard`` entities with provenance links to chunks and
graph nodes, plus model-driven contradiction/redundancy detection
against existing cycle evidence.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.adapters.embeddings.router import EmbeddingsRouter
from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.analysis import (
    EvidenceCard,
    GraphNode,
    PaperAnalysisPacket,
    PaperChunk,
)

log = get_logger("analysis.evidence_extraction")


# ---------------------------------------------------------------------------
# Structured output models
# ---------------------------------------------------------------------------


class ExtractedEvidence(BaseModel):
    """One evidence claim extracted by the LLM."""

    evidence_type: str  # finding, method_claim, dataset_availability, limitation, comparison
    claim: str
    supporting_text: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractionOutput(BaseModel):
    """Batch of evidence extracted from one paper."""

    evidence: list[ExtractedEvidence] = Field(default_factory=list)


class ContradictionResult(BaseModel):
    """Result of comparing two evidence claims."""

    relationship: str  # contradictory, redundant, independent
    reason: str = ""
    model_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


async def extract_evidence(
    db: Session,
    *,
    packet: PaperAnalysisPacket,
    chunks: list[PaperChunk],
    nodes: list[GraphNode],
    charter_id: UUID,
    cycle_id: UUID,
    concurrency: int = 4,
) -> list[EvidenceCard]:
    """Extract evidence cards from an analysis packet with contradiction detection."""
    router = ModelRouter()

    # 1. Extract evidence claims via LLM
    context = _build_extraction_context(packet, chunks, nodes)
    extraction = await router.complete_structured(
        ModelRole.paper_analysis,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        response_model=ExtractionOutput,
    )

    if not extraction.evidence:
        log.info("no_evidence_extracted", paper_card_id=str(packet.paper_card_id))
        return []

    # 2. Build evidence cards with provenance
    chunk_ids = [str(c.id) for c in chunks[:10]]  # Top chunks as provenance
    node_ids = [str(n.id) for n in nodes[:10]]  # Top nodes as provenance

    cards: list[EvidenceCard] = []
    for ev in extraction.evidence:
        card = EvidenceCard(
            id=uuid7(),
            charter_id=charter_id,
            cycle_id=cycle_id,
            paper_card_id=packet.paper_card_id,
            analysis_packet_id=packet.id,
            evidence_type=ev.evidence_type,
            claim=ev.claim,
            supporting_text=ev.supporting_text,
            source_chunk_ids=chunk_ids,
            source_graph_node_ids=node_ids,
            confidence=ev.confidence,
            analysis_depth="full",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        cards.append(card)

    # 3. Embed evidence claims
    await _embed_evidence(cards, router)

    # 4. Detect contradictions/redundancy against existing cycle evidence
    await _detect_contradictions(
        db, cards, cycle_id, router, concurrency=concurrency,
    )

    # 5. Persist
    for card in cards:
        db.add(card)
    db.flush()

    log.info(
        "evidence_extracted",
        card_count=len(cards),
        paper_card_id=str(packet.paper_card_id),
    )
    return cards


async def _embed_evidence(
    cards: list[EvidenceCard],
    router: Any,
) -> None:
    """Embed evidence claims for similarity pre-filtering."""
    emb_router = EmbeddingsRouter()
    texts = [c.claim for c in cards]
    if not texts:
        return

    embeddings = await emb_router.embed(texts)
    for card, emb in zip(cards, embeddings, strict=False):
        if emb:
            card.embedding = emb


async def _detect_contradictions(
    db: Session,
    new_cards: list[EvidenceCard],
    cycle_id: UUID,
    router: Any,
    *,
    concurrency: int = 4,
    similarity_threshold: float = 0.7,
) -> None:
    """Compare new evidence against existing cycle evidence.

    Canonical prefilter: embedding cosine similarity > threshold via pgvector.
    Then LLM classifies each candidate pair.
    """
    sem = asyncio.Semaphore(concurrency)

    for card in new_cards:
        if card.embedding is None:
            continue

        # Query existing evidence with similar embeddings
        candidates = db.execute(
            select(EvidenceCard).where(
                EvidenceCard.cycle_id == cycle_id,
                EvidenceCard.embedding.isnot(None),
                EvidenceCard.embedding.cosine_distance(card.embedding)
                < (1.0 - similarity_threshold),
            ).limit(10)
        ).scalars().all()

        if not candidates:
            continue

        # LLM-classify each pair
        contradictions: list[dict[str, Any]] = []

        async def _classify(
            existing: EvidenceCard,
            current_card: EvidenceCard = card,
            results: list[dict[str, Any]] = contradictions,
        ) -> None:
            async with sem:
                try:
                    cr = await router.complete_structured(
                        ModelRole.paper_analysis,
                        messages=[
                            {"role": "system", "content": _CONTRADICTION_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"Claim A: {current_card.claim}\n\n"
                                    f"Claim B: {existing.claim}"
                                ),
                            },
                        ],
                        response_model=ContradictionResult,
                    )
                    if cr.relationship == "contradictory":
                        results.append({
                            "evidence_id": str(existing.id),
                            "reason": cr.reason,
                            "model_confidence": cr.model_confidence,
                        })
                    elif cr.relationship == "redundant":
                        group = existing.redundancy_group or str(existing.id)
                        current_card.redundancy_group = group
                except Exception:
                    log.debug(
                        "contradiction_check_failed",
                        exc_info=True,
                    )

        tasks = [_classify(c) for c in candidates]
        await asyncio.gather(*tasks)

        if contradictions:
            card.contradiction_flags = {"contradicts": contradictions}


def _build_extraction_context(
    packet: PaperAnalysisPacket,
    chunks: list[PaperChunk],
    nodes: list[GraphNode],
) -> str:
    parts = [
        f"## Paper Summary\n{packet.summary}",
    ]

    if packet.key_contributions:
        contribs = "\n".join(f"- {c}" for c in packet.key_contributions)
        parts.append(f"## Key Contributions\n{contribs}")

    if packet.methods_used:
        methods = "\n".join(f"- {m}" for m in packet.methods_used)
        parts.append(f"## Methods\n{methods}")

    # Include top chunks for grounding
    if chunks:
        chunk_text = "\n\n".join(
            f"[{c.section_path or c.chunk_type}] {c.content[:300]}"
            for c in chunks[:10]
        )
        parts.append(f"## Key Passages\n{chunk_text}")

    # Include graph nodes for entity context
    if nodes:
        node_text = "\n".join(
            f"- [{n.node_type}] {n.label}: {n.description or ''}"
            for n in nodes[:15]
        )
        parts.append(f"## Extracted Entities\n{node_text}")

    return "\n\n".join(parts)


_EXTRACTION_SYSTEM_PROMPT = """\
You are a research evidence extraction system. Given a structured analysis
of a research paper, extract discrete evidence claims.

For each piece of evidence, provide:
- **evidence_type**: one of: finding, method_claim, dataset_availability, limitation, comparison
- **claim**: A concise, self-contained evidence statement
- **supporting_text**: The specific text that supports this claim (if available)
- **confidence**: Your confidence in this evidence (0.0-1.0)

Focus on:
- Key empirical findings and results
- Novel methodological claims
- Dataset availability and characteristics
- Known limitations acknowledged by the authors
- Comparisons with prior work

Extract 5-15 evidence claims per paper, prioritizing quality over quantity.
"""

_CONTRADICTION_PROMPT = """\
You are comparing two research evidence claims. Classify their relationship:

- **contradictory**: The claims make opposing assertions about the same topic
- **redundant**: The claims say essentially the same thing
- **independent**: The claims are about different topics or compatible

Provide:
- relationship: contradictory, redundant, or independent
- reason: Brief explanation
- model_confidence: Your confidence in this classification (0.0-1.0)
"""
