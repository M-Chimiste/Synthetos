"""LLM-driven typed graph extraction from paper chunks.

Processes chunks in batches with semaphore-bounded concurrency and
extracts concept, method, experiment, dataset, figure, table, and
equation nodes plus typed relations.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.analysis import GraphEdge, GraphNode, PaperChunk

log = get_logger("analysis.graph_extraction")


# ---------------------------------------------------------------------------
# Structured output models for LLM extraction
# ---------------------------------------------------------------------------


class ExtractedNode(BaseModel):
    """A graph node extracted by the LLM."""

    node_type: str
    label: str
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedEdge(BaseModel):
    """A relation extracted by the LLM."""

    source_label: str
    target_label: str
    edge_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.8


class ChunkExtractionResult(BaseModel):
    """Extraction result for one chunk."""

    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction logic
# ---------------------------------------------------------------------------


async def extract_graph(
    db: Session,
    *,
    chunks: list[PaperChunk],
    analysis_session_id: UUID,
    paper_card_id: UUID,
    concurrency: int = 4,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Extract typed graph from chunks via LLM.

    Returns (nodes, edges) persisted to the database.
    """
    router = ModelRouter()
    sem = asyncio.Semaphore(concurrency)
    all_results: list[tuple[PaperChunk, ChunkExtractionResult]] = []

    async def _extract_one(chunk: PaperChunk) -> None:
        async with sem:
            try:
                result = await router.complete_structured(
                    ModelRole.graph_extraction,
                    messages=[
                        {
                            "role": "system",
                            "content": _EXTRACTION_SYSTEM_PROMPT,
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Extract graph entities and relations from "
                                f"this paper chunk:\n\n{chunk.content}"
                            ),
                        },
                    ],
                    response_model=ChunkExtractionResult,
                )
                all_results.append((chunk, result))
            except Exception:
                log.warning(
                    "chunk_extraction_failed",
                    chunk_id=str(chunk.id),
                    exc_info=True,
                )

    # Run extractions concurrently
    tasks = [_extract_one(chunk) for chunk in chunks]
    await asyncio.gather(*tasks)

    # Deduplicate and persist nodes
    nodes_by_label: dict[str, GraphNode] = {}
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []

    for chunk, extraction in all_results:
        for en in extraction.nodes:
            key = f"{en.node_type}::{en.label}"
            if key not in nodes_by_label:
                node = GraphNode(
                    id=uuid7(),
                    analysis_session_id=analysis_session_id,
                    paper_card_id=paper_card_id,
                    node_type=en.node_type,
                    label=en.label,
                    description=en.description,
                    properties=en.properties,
                    provenance={
                        "source_chunk_ids": [str(chunk.id)],
                        "extraction_model": "graph_extraction",
                    },
                    created_at=utcnow(),
                )
                db.add(node)
                nodes_by_label[key] = node
                all_nodes.append(node)
            else:
                # Merge provenance: add this chunk as an additional source
                existing = nodes_by_label[key]
                prov = existing.provenance or {}
                chunk_ids = prov.get("source_chunk_ids", [])
                chunk_ids.append(str(chunk.id))
                existing.provenance = {**prov, "source_chunk_ids": chunk_ids}

    db.flush()  # Ensure nodes have IDs

    # Persist edges
    for _chunk, extraction in all_results:
        for ee in extraction.edges:
            # Try to find source and target across all node types
            src_node = None
            tgt_node = None
            for nt in ("concept", "method", "experiment", "dataset",
                       "figure", "table", "equation", "section", "paper"):
                if src_node is None:
                    src_node = nodes_by_label.get(f"{nt}::{ee.source_label}")
                if tgt_node is None:
                    tgt_node = nodes_by_label.get(f"{nt}::{ee.target_label}")

            if src_node is None or tgt_node is None:
                continue

            edge = GraphEdge(
                id=uuid7(),
                analysis_session_id=analysis_session_id,
                source_node_id=src_node.id,
                target_node_id=tgt_node.id,
                edge_type=ee.edge_type,
                properties=ee.properties,
                provenance={"extraction_model": "graph_extraction"},
                confidence=ee.confidence,
                created_at=utcnow(),
            )
            db.add(edge)
            all_edges.append(edge)

    db.flush()
    log.info(
        "graph_extracted",
        node_count=len(all_nodes),
        edge_count=len(all_edges),
    )
    return all_nodes, all_edges


async def project_to_graph_adapter(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    graph_name: str,
    db_url: str,
) -> bool:
    """Project relational graph data into AGE (if available).

    Returns True if projection succeeded, False if adapter is unavailable.
    """
    from libs.adapters.graph import get_graph_adapter

    adapter = await get_graph_adapter(db_url)

    try:
        await adapter.create_graph(graph_name)
    except Exception:
        log.info("graph_projection_skipped", reason="create_graph_failed")
        return False

    # Map relational IDs to graph-internal IDs
    id_map: dict[str, str] = {}

    for node in nodes:
        try:
            age_id = await adapter.add_node(
                graph_name,
                label=node.node_type,
                properties={
                    "id": str(node.id),
                    "label": node.label,
                    "description": node.description or "",
                },
            )
            node.age_node_id = age_id
            id_map[str(node.id)] = age_id
        except Exception:
            log.debug("node_projection_failed", node_id=str(node.id))

    for edge in edges:
        src_age = id_map.get(str(edge.source_node_id))
        tgt_age = id_map.get(str(edge.target_node_id))
        if src_age and tgt_age:
            try:
                age_id = await adapter.add_edge(
                    graph_name,
                    from_id=src_age,
                    to_id=tgt_age,
                    label=edge.edge_type,
                    properties={"id": str(edge.id), "confidence": edge.confidence},
                )
                edge.age_edge_id = age_id
            except Exception:
                log.debug("edge_projection_failed", edge_id=str(edge.id))

    return True


_EXTRACTION_SYSTEM_PROMPT = """\
You are a research paper analysis system. Extract structured graph entities
and relations from the given paper chunk.

For each chunk, extract:

**Nodes** (entities):
- concept: Key ideas, theories, or principles
- method: Algorithms, techniques, or approaches
- experiment: Experimental setups or evaluation procedures
- dataset: Named datasets or data sources
- figure: Referenced figures
- table: Referenced tables
- equation: Key equations or formulas

**Edges** (relations between entities):
- defines: A section or passage defines a concept
- proposes: The paper proposes a method
- uses: An experiment uses a dataset or method
- evaluates: An experiment evaluates a method
- illustrates: A figure illustrates a concept
- compares: A comparison between methods or results
- depends_on: A method depends on another

Return only entities and relations that are explicitly mentioned or clearly
implied in the chunk text. Use concise, specific labels.
"""
