"""Graph adapters for typed paper graph storage and traversal.

Provides two implementations behind a common ``GraphAdapter`` protocol:

* ``AgeGraphAdapter`` -- uses Apache AGE (Cypher-over-SQL) when available.
* ``RelationalGraphAdapter`` -- fallback using SQL joins + recursive CTEs.

Use ``get_graph_adapter()`` to select the best available implementation.
"""

from __future__ import annotations

from libs.adapters.graph.base import GraphAdapter, GraphNode, GraphPath
from libs.core.logging import get_logger

log = get_logger("adapters.graph")

_cached_adapter: GraphAdapter | None = None


async def get_graph_adapter(db_url: str) -> GraphAdapter:
    """Return the best available graph adapter, cached after first probe.

    Tries AGE first; falls back to relational if AGE is unavailable.
    """
    global _cached_adapter
    if _cached_adapter is not None:
        return _cached_adapter

    from libs.adapters.graph.age_adapter import AgeGraphAdapter

    age = AgeGraphAdapter(db_url)
    if await age.health():
        log.info("graph_adapter_selected", adapter="age")
        _cached_adapter = age
        return age

    await age.close()

    from libs.adapters.graph.relational_adapter import RelationalGraphAdapter

    log.info("graph_adapter_selected", adapter="relational")
    rel = RelationalGraphAdapter(db_url)
    _cached_adapter = rel
    return rel


__all__ = [
    "GraphAdapter",
    "GraphNode",
    "GraphPath",
    "get_graph_adapter",
]
