"""Graph-aware QA and entity locate support.

Three-stage QA:
1. Retrieve top-k relevant chunks via pgvector embedding similarity
2. Expand graph neighbors via GraphAdapter
3. Synthesize answer via LLM with full provenance
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.adapters.embeddings.router import EmbeddingsRouter
from libs.adapters.llm.router import ModelRouter
from libs.core.logging import get_logger
from libs.schemas.analysis import ChunkRef, LocateMatch, NodeRef, QAResponse
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.analysis import AnalysisSession, GraphNode, PaperChunk

log = get_logger("analysis.graph_qa")


class QAContext(BaseModel):
    """Internal context assembled for QA."""

    chunks: list[ChunkRef] = Field(default_factory=list)
    nodes: list[NodeRef] = Field(default_factory=list)
    text: str = ""


async def answer_question(
    db: Session,
    *,
    paper_card_id: UUID,
    question: str,
    max_chunks: int = 10,
    expand_graph: bool = True,
    db_url: str | None = None,
) -> QAResponse:
    """Answer a question about a paper using graph-aware retrieval."""
    emb_router = EmbeddingsRouter()
    llm_router = ModelRouter()
    session_id = _latest_completed_session_id(db, paper_card_id)
    if session_id is None:
        raise ValueError(f"no completed analysis session for paper {paper_card_id}")

    # 1. Embed the question
    q_embedding = (await emb_router.embed([question]))[0]

    # 2. Retrieve top-k chunks by embedding similarity
    chunk_rows = list(
        db.execute(
        select(PaperChunk)
        .where(
            PaperChunk.paper_card_id == paper_card_id,
            PaperChunk.analysis_session_id == session_id,
            PaperChunk.embedding.isnot(None),
        )
        .order_by(PaperChunk.embedding.cosine_distance(q_embedding))
        .limit(max_chunks)
    ).scalars().all()
    )

    chunk_refs = [
        ChunkRef(
            chunk_id=c.id,
            section_path=c.section_path,
            ordinal=c.ordinal,
            snippet=c.content[:200],
        )
        for c in chunk_rows
    ]

    # 3. Expand graph neighbors if requested
    node_refs: list[NodeRef] = []
    if expand_graph and chunk_rows:
        node_refs = _expand_graph_context(db, chunk_rows)

    # 4. Synthesize answer via LLM
    context_text = _build_qa_context(chunk_rows, node_refs)

    answer_resp = await llm_router.complete(
        ModelRole.paper_analysis,
        messages=[
            {"role": "system", "content": _QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Context:\n{context_text}"
                ),
            },
        ],
    )

    return QAResponse(
        answer=answer_resp.content,
        supporting_chunks=chunk_refs,
        supporting_nodes=node_refs,
        confidence=0.7,  # Could be refined by the LLM
    )


async def locate_entity(
    db: Session,
    *,
    paper_card_id: UUID,
    entity_type: str,
    query: str,
) -> list[LocateMatch]:
    """Locate where an entity appears in a paper."""
    session_id = _latest_completed_session_id(db, paper_card_id)
    if session_id is None:
        return []

    # Find matching graph nodes
    nodes = db.execute(
        select(GraphNode).where(
            GraphNode.paper_card_id == paper_card_id,
            GraphNode.analysis_session_id == session_id,
            GraphNode.node_type == entity_type,
            GraphNode.label.ilike(f"%{query}%"),
        ).limit(10)
    ).scalars().all()

    matches: list[LocateMatch] = []
    for node in nodes:
        # Find chunks linked to this node via provenance
        prov = node.provenance or {}
        chunk_ids = prov.get("source_chunk_ids", [])

        chunk_refs: list[ChunkRef] = []
        if chunk_ids:
            linked_chunks = db.execute(
                select(PaperChunk).where(
                    PaperChunk.id.in_([UUID(cid) for cid in chunk_ids[:5]])
                )
            ).scalars().all()

            chunk_refs = [
                ChunkRef(
                    chunk_id=c.id,
                    section_path=c.section_path,
                    ordinal=c.ordinal,
                    snippet=c.content[:200],
                )
                for c in linked_chunks
            ]

        matches.append(LocateMatch(
            node=NodeRef(
                node_id=node.id,
                node_type=node.node_type,
                label=node.label,
            ),
            chunks=chunk_refs,
        ))

    return matches


def _expand_graph_context(
    db: Session,
    chunks: list[PaperChunk],
) -> list[NodeRef]:
    """Find graph nodes linked to the retrieved chunks."""
    # Collect chunk IDs
    chunk_id_strs = [str(c.id) for c in chunks]

    # Find nodes whose provenance references these chunks
    # Using a simple JSONB containment query
    all_nodes: list[GraphNode] = []
    if chunks:
        session_id = chunks[0].analysis_session_id
        nodes = db.execute(
            select(GraphNode).where(
                GraphNode.analysis_session_id == session_id,
            ).limit(30)
        ).scalars().all()

        for node in nodes:
            prov = node.provenance or {}
            source_chunks = prov.get("source_chunk_ids", [])
            if any(cid in chunk_id_strs for cid in source_chunks):
                all_nodes.append(node)

    return [
        NodeRef(
            node_id=n.id,
            node_type=n.node_type,
            label=n.label,
        )
        for n in all_nodes[:15]
    ]


def _build_qa_context(
    chunks: list[PaperChunk],
    nodes: list[NodeRef],
) -> str:
    parts: list[str] = []

    if chunks:
        for c in chunks:
            header = c.section_path or c.chunk_type
            parts.append(f"[{header}] {c.content[:500]}")

    if nodes:
        node_text = "\n".join(
            f"- [{n.node_type}] {n.label}" for n in nodes
        )
        parts.append(f"\nRelated entities:\n{node_text}")

    return "\n\n".join(parts)


def _latest_completed_session_id(db: Session, paper_card_id: UUID) -> UUID | None:
    session = db.execute(
        select(AnalysisSession.id)
        .where(
            AnalysisSession.paper_card_id == paper_card_id,
            AnalysisSession.status == "completed",
        )
        .order_by(AnalysisSession.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return session


_QA_SYSTEM_PROMPT = """\
You are a research paper QA system. Answer the user's question based
strictly on the provided context from the paper. Include specific
references to sections or entities when possible.

If the context does not contain enough information to answer the
question, say so clearly rather than speculating.
"""
