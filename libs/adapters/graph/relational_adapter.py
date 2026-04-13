"""Relational graph adapter -- fallback when Apache AGE is unavailable.

Uses SQL joins and recursive CTEs over the canonical ``graph_nodes`` and
``graph_edges`` relational tables.  Slower for deep traversal than AGE,
but always available.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from libs.adapters.graph.base import GraphNode, GraphPath
from libs.core.logging import get_logger

log = get_logger("adapters.graph.relational")


class RelationalGraphAdapter:
    """Graph adapter backed by relational graph_nodes / graph_edges tables."""

    def __init__(self, db_url: str) -> None:
        self._conninfo = db_url.replace(
            "postgresql+psycopg://", "postgresql://"
        ).replace("postgresql://", "postgresql://")
        self._conn: Any | None = None

    async def _get_conn(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = await psycopg.AsyncConnection.connect(
                self._conninfo, row_factory=cast(Any, dict_row)
            )
        return self._conn

    async def health(self) -> bool:
        """Relational adapter is always available if DB is reachable."""
        try:
            conn = await self._get_conn()
            await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def create_graph(self, graph_name: str) -> None:
        """No-op for relational adapter. Graph identity is implicit via session ID."""
        log.debug("relational_create_graph", graph=graph_name)

    async def drop_graph(self, graph_name: str) -> None:
        """No-op for relational adapter. Cleanup happens via CASCADE deletes."""
        log.debug("relational_drop_graph", graph=graph_name)

    async def add_node(
        self,
        graph_name: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        """No-op: nodes are written directly to graph_nodes table by operators.

        Returns a placeholder ID since the relational adapter doesn't maintain
        separate graph-internal IDs.
        """
        return properties.get("id", "")

    async def add_edge(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        """No-op: edges are written directly to graph_edges table by operators."""
        return properties.get("id", "")

    async def query_neighbors(
        self,
        graph_name: str,
        node_id: str,
        edge_labels: list[str] | None = None,
        max_depth: int = 1,
    ) -> list[GraphNode]:
        """Find neighbors using recursive CTE over graph_edges."""
        conn = await self._get_conn()

        edge_filter = ""
        params: dict[str, Any] = {"node_id": UUID(node_id), "max_depth": max_depth}
        if edge_labels:
            edge_filter = "AND e.edge_type = ANY(%(edge_labels)s)"
            params["edge_labels"] = edge_labels

        query = f"""
        WITH RECURSIVE neighbors AS (
            SELECT
                n.id, n.label, n.node_type, n.properties,
                1 AS depth
            FROM graph_edges e
            JOIN graph_nodes n ON n.id = e.target_node_id
            WHERE e.source_node_id = %(node_id)s
            {edge_filter}

            UNION

            SELECT
                n2.id, n2.label, n2.node_type, n2.properties,
                nb.depth + 1
            FROM neighbors nb
            JOIN graph_edges e2 ON e2.source_node_id = nb.id
            JOIN graph_nodes n2 ON n2.id = e2.target_node_id
            WHERE nb.depth < %(max_depth)s
            {"AND e2.edge_type = ANY(%(edge_labels)s)" if edge_labels else ""}
        )
        SELECT DISTINCT id, label, node_type, properties
        FROM neighbors
        """

        result = await conn.execute(query, params)
        nodes: list[GraphNode] = []
        async for row in result:
            nodes.append(GraphNode(
                id=str(row["id"]),
                label=row["label"],
                node_type=row["node_type"],
                properties=row["properties"] or {},
            ))
        return nodes

    async def query_path(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
    ) -> list[GraphPath]:
        """Find shortest path using BFS via recursive CTE."""
        conn = await self._get_conn()

        query = """
        WITH RECURSIVE path_search AS (
            SELECT
                e.target_node_id AS current_id,
                ARRAY[e.source_node_id, e.target_node_id] AS path,
                1 AS depth
            FROM graph_edges e
            WHERE e.source_node_id = %(from_id)s

            UNION ALL

            SELECT
                e.target_node_id,
                ps.path || e.target_node_id,
                ps.depth + 1
            FROM path_search ps
            JOIN graph_edges e ON e.source_node_id = ps.current_id
            WHERE ps.depth < 10
            AND NOT e.target_node_id = ANY(ps.path)
        )
        SELECT path, depth FROM path_search
        WHERE current_id = %(to_id)s
        ORDER BY depth
        LIMIT 1
        """

        result = await conn.execute(
            query, {"from_id": UUID(from_id), "to_id": UUID(to_id)}
        )
        paths: list[GraphPath] = []
        async for row in result:
            # Build GraphNode list from path UUIDs
            node_ids = row["path"]
            nodes: list[GraphNode] = []
            for nid in node_ids:
                n_result = await conn.execute(
                    "SELECT id, label, node_type, properties "
                    "FROM graph_nodes WHERE id = %s",
                    (nid,),
                )
                n_row = await n_result.fetchone()
                if n_row:
                    nodes.append(GraphNode(
                        id=str(n_row["id"]),
                        label=n_row["label"],
                        node_type=n_row["node_type"],
                        properties=n_row["properties"] or {},
                    ))
            paths.append(GraphPath(nodes=nodes, length=row["depth"]))
        return paths

    async def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            await self._conn.close()
            self._conn = None
