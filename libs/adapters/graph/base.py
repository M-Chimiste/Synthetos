"""Graph adapter protocol and shared DTOs."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class GraphNode(BaseModel):
    """A node returned from a graph query."""

    id: str
    label: str
    node_type: str
    properties: dict[str, Any] = {}


class GraphPath(BaseModel):
    """A path between two nodes."""

    nodes: list[GraphNode] = []
    edges: list[dict[str, Any]] = []
    length: int = 0


@runtime_checkable
class GraphAdapter(Protocol):
    """Protocol that all graph storage adapters must satisfy."""

    async def create_graph(self, graph_name: str) -> None:
        """Create a named graph (no-op if it exists)."""
        ...

    async def drop_graph(self, graph_name: str) -> None:
        """Drop a named graph if it exists."""
        ...

    async def add_node(
        self,
        graph_name: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        """Add a node and return its graph-internal ID."""
        ...

    async def add_edge(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        """Add an edge and return its graph-internal ID."""
        ...

    async def query_neighbors(
        self,
        graph_name: str,
        node_id: str,
        edge_labels: list[str] | None = None,
        max_depth: int = 1,
    ) -> list[GraphNode]:
        """Return nodes reachable from ``node_id`` within ``max_depth``."""
        ...

    async def query_path(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
    ) -> list[GraphPath]:
        """Return shortest paths between two nodes."""
        ...

    async def health(self) -> bool:
        """Return True if this adapter's backend is available."""
        ...

    async def close(self) -> None:
        """Release held resources."""
        ...
