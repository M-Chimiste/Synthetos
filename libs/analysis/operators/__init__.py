"""Phase 2 analysis operators.

Each operator is a synchronous callable that conforms to the
``OperatorHandler`` contract registered in :mod:`apps.worker.executor`.
Internally an operator opens a sync DB session, loads the analysis
session it needs, and runs any async work (LLM calls, HTTP requests,
embedding queries) via :func:`asyncio.run`.

The operators form a chain:

    analysis_ingest
        -> analysis_chunk
            -> analysis_graph_extract
                -> analysis_coverage
                    -> analysis_review
                        -> analysis_evidence

Each operator enqueues the next job on success.  The chain stops if any
step fails and the failing job is marked failed by the worker.
"""

from libs.analysis.operators.chunk import analysis_chunk_operator
from libs.analysis.operators.coverage import analysis_coverage_operator
from libs.analysis.operators.evidence import analysis_evidence_operator
from libs.analysis.operators.graph_extract import analysis_graph_extract_operator
from libs.analysis.operators.ingest import analysis_ingest_operator
from libs.analysis.operators.review import analysis_review_operator

__all__ = [
    "analysis_chunk_operator",
    "analysis_coverage_operator",
    "analysis_evidence_operator",
    "analysis_graph_extract_operator",
    "analysis_ingest_operator",
    "analysis_review_operator",
]


def register(register_operator) -> None:
    """Register all six analysis operators with the worker registry."""
    register_operator("analysis_ingest", analysis_ingest_operator)
    register_operator("analysis_chunk", analysis_chunk_operator)
    register_operator("analysis_graph_extract", analysis_graph_extract_operator)
    register_operator("analysis_coverage", analysis_coverage_operator)
    register_operator("analysis_review", analysis_review_operator)
    register_operator("analysis_evidence", analysis_evidence_operator)
