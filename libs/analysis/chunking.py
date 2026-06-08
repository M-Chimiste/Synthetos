"""Structure-aware chunking for ingested documents.

Reads from ``ingested_documents.normalized_*`` fields and produces
``paper_chunks`` rows with embeddings.  Never re-fetches the paper.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.adapters.embeddings.router import EmbeddingsRouter
from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.storage.models.analysis import IngestedDocument, PaperChunk

log = get_logger("analysis.chunking")


def chunk_document(
    db: Session,
    *,
    doc: IngestedDocument,
    analysis_session_id: UUID,
    paper_card_id: UUID,
    max_chunks: int = 500,
) -> list[PaperChunk]:
    """Split an ingested document into structure-aware chunks.

    Returns the list of persisted ``PaperChunk`` rows (without embeddings --
    those are added by a separate embedding pass).
    """
    chunks: list[PaperChunk] = []
    ordinal = 0

    # 1. Section/paragraph chunks
    for section in doc.normalized_sections or []:
        heading = section.get("heading", "")
        content = section.get("content", "")
        level = section.get("level", 1)

        if not content.strip():
            continue

        # Split long sections into paragraph-level chunks
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]

        if len(paragraphs) <= 1:
            # Keep as a single section chunk
            chunk = _make_chunk(
                db,
                analysis_session_id=analysis_session_id,
                paper_card_id=paper_card_id,
                chunk_type="section",
                section_path=heading,
                ordinal=ordinal,
                content=content,
                metadata={"level": level},
            )
            chunks.append(chunk)
            ordinal += 1
        else:
            for para in paragraphs:
                if len(chunks) >= max_chunks:
                    break
                chunk = _make_chunk(
                    db,
                    analysis_session_id=analysis_session_id,
                    paper_card_id=paper_card_id,
                    chunk_type="paragraph",
                    section_path=heading,
                    ordinal=ordinal,
                    content=para,
                    metadata={"level": level, "parent_section": heading},
                )
                chunks.append(chunk)
                ordinal += 1

        if len(chunks) >= max_chunks:
            break

    # 2. Figure chunks
    for fig in doc.normalized_figures or []:
        if len(chunks) >= max_chunks:
            break
        caption = fig.get("caption", "")
        desc = fig.get("content_description", "")
        content = f"Figure {fig.get('id', '')}: {caption}"
        if desc and desc != caption:
            content += f"\n{desc}"

        chunk = _make_chunk(
            db,
            analysis_session_id=analysis_session_id,
            paper_card_id=paper_card_id,
            chunk_type="figure",
            section_path=None,
            ordinal=ordinal,
            content=content,
            metadata={"figure_id": fig.get("id"), "page": fig.get("page")},
        )
        chunks.append(chunk)
        ordinal += 1

    # 3. Table chunks
    for tbl in doc.normalized_tables or []:
        if len(chunks) >= max_chunks:
            break
        caption = tbl.get("caption", "")
        desc = tbl.get("content_description", "")
        content = f"Table {tbl.get('id', '')}: {caption}"
        if desc and desc != caption:
            content += f"\n{desc}"

        chunk = _make_chunk(
            db,
            analysis_session_id=analysis_session_id,
            paper_card_id=paper_card_id,
            chunk_type="table",
            section_path=None,
            ordinal=ordinal,
            content=content,
            metadata={"table_id": tbl.get("id"), "page": tbl.get("page")},
        )
        chunks.append(chunk)
        ordinal += 1

    # 4. Equation chunks
    for eq in doc.normalized_equations or []:
        if len(chunks) >= max_chunks:
            break
        content = f"Equation {eq.get('id', '')}: {eq.get('latex', '')}"
        ctx = eq.get("context")
        if ctx:
            content += f"\nContext: {ctx}"

        chunk = _make_chunk(
            db,
            analysis_session_id=analysis_session_id,
            paper_card_id=paper_card_id,
            chunk_type="equation",
            section_path=None,
            ordinal=ordinal,
            content=content,
            metadata={"equation_id": eq.get("id"), "page": eq.get("page")},
        )
        chunks.append(chunk)
        ordinal += 1

    db.flush()
    log.info("chunks_created", count=len(chunks))
    return chunks


async def embed_chunks(
    chunks: list[PaperChunk],
    db: Session,
) -> int:
    """Embed all chunks via the EmbeddingsRouter.

    Returns the number of chunks successfully embedded.
    """
    router = EmbeddingsRouter()
    texts = [c.content for c in chunks]

    if not texts:
        return 0

    embeddings = await router.embed(texts)
    embedded_count = 0
    for chunk, emb in zip(chunks, embeddings, strict=False):
        if emb:
            chunk.embedding = emb
            embedded_count += 1

    db.flush()
    log.info("chunks_embedded", count=embedded_count)
    return embedded_count


def _make_chunk(
    db: Session,
    *,
    analysis_session_id: UUID,
    paper_card_id: UUID,
    chunk_type: str,
    section_path: str | None,
    ordinal: int,
    content: str,
    metadata: dict | None = None,
) -> PaperChunk:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    chunk = PaperChunk(
        id=uuid7(),
        analysis_session_id=analysis_session_id,
        paper_card_id=paper_card_id,
        chunk_type=chunk_type,
        section_path=section_path,
        ordinal=ordinal,
        content=content,
        content_hash=content_hash,
        chunk_metadata=metadata,
        created_at=utcnow(),
    )
    db.add(chunk)
    return chunk
