"""Phase 1 discovery operators.

Each operator is a synchronous callable that conforms to the
``OperatorHandler`` contract registered in :mod:`apps.worker.executor`.
Internally an operator opens a sync DB session, loads the discovery
session/profile/cards it needs, and runs any async work (LLM calls,
HTTP requests, embedding queries) via :func:`asyncio.run`.

The operators form a chain:

    discovery_intake
        -> discovery_search
            -> discovery_rerank
                -> discovery_analyze
                    -> discovery_finalize

Each operator enqueues the next job on success.  The chain stops if any
step fails and the failing job is marked failed by the worker (Phase 0
behavior, untouched here).
"""

from libs.discovery.operators.analyze import discovery_analyze_operator
from libs.discovery.operators.finalize import discovery_finalize_operator
from libs.discovery.operators.intake import discovery_intake_operator
from libs.discovery.operators.rerank import discovery_rerank_operator
from libs.discovery.operators.search import discovery_search_operator

__all__ = [
    "discovery_analyze_operator",
    "discovery_finalize_operator",
    "discovery_intake_operator",
    "discovery_rerank_operator",
    "discovery_search_operator",
]


def register(register_operator) -> None:
    """Register all five discovery operators with the worker registry."""
    register_operator("discovery_intake", discovery_intake_operator)
    register_operator("discovery_search", discovery_search_operator)
    register_operator("discovery_rerank", discovery_rerank_operator)
    register_operator("discovery_analyze", discovery_analyze_operator)
    register_operator("discovery_finalize", discovery_finalize_operator)
