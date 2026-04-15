"""Apache AGE graph adapter.

Uses Cypher-over-SQL via ``ag_catalog`` functions in the same PostgreSQL
instance that hosts the rest of the Synthetos data.  One AGE graph is
created per paper (named ``paper_<short_id>``).
"""

from __future__ import annotations

import json
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from libs.adapters.graph.base import GraphNode, GraphPath
from libs.core.logging import get_logger

log = get_logger("adapters.graph.age")


class AgeGraphAdapter:
    """Graph adapter backed by Apache AGE."""

    def __init__(self, db_url: str) -> None:
        # Convert SQLAlchemy-style URL to psycopg conninfo
        self._conninfo = db_url.replace(
            "postgresql+psycopg://", "postgresql://"
        ).replace("postgresql://", "postgresql://")
        self._conn: Any | None = None

    async def _get_conn(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = await psycopg.AsyncConnection.connect(
                self._conninfo, row_factory=cast(Any, dict_row)
            )
            # Load AGE extension into the session
            await self._conn.execute(
                "LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;"
            )
        return self._conn

    async def health(self) -> bool:
        """Check if AGE extension is available."""
        try:
            conn = await self._get_conn()
            result = await conn.execute(
                "SELECT extname FROM pg_extension WHERE extname = 'age'"
            )
            row = await result.fetchone()
            return row is not None
        except Exception:
            log.debug("age_health_check_failed", exc_info=True)
            return False

    async def create_graph(self, graph_name: str) -> None:
        conn = await self._get_conn()
        # Check if graph exists first
        result = await conn.execute(
            "SELECT * FROM ag_catalog.ag_graph WHERE name = %s",
            (graph_name,),
        )
        if await result.fetchone() is None:
            await conn.execute(
                "SELECT ag_catalog.create_graph(%s)",
                (graph_name,),
            )
            await conn.execute("COMMIT")
            log.info("age_graph_created", graph=graph_name)

    async def drop_graph(self, graph_name: str) -> None:
        conn = await self._get_conn()
        try:
            await conn.execute(
                "SELECT ag_catalog.drop_graph(%s, true)",
                (graph_name,),
            )
            await conn.execute("COMMIT")
        except Exception:
            log.debug("age_drop_graph_failed", graph=graph_name, exc_info=True)

    async def add_node(
        self,
        graph_name: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        conn = await self._get_conn()
        # AGE requires Cypher via ag_catalog.cypher()

        props_json = json.dumps(properties)
        cypher = f"CREATE (n:{label} {props_json}) RETURN id(n)"
        result = await conn.execute(
            f"SELECT * FROM ag_catalog.cypher('{graph_name}', $$ {cypher} $$) AS (id agtype)"
        )
        row = await result.fetchone()
        await conn.execute("COMMIT")
        node_id = str(row["id"]) if row else ""
        return node_id

    async def add_edge(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
        label: str,
        properties: dict[str, Any],
    ) -> str:
        conn = await self._get_conn()
        import json

        props_json = json.dumps(properties)
        cypher = (
            f"MATCH (a), (b) WHERE id(a) = {from_id} AND id(b) = {to_id} "
            f"CREATE (a)-[r:{label} {props_json}]->(b) RETURN id(r)"
        )
        result = await conn.execute(
            f"SELECT * FROM ag_catalog.cypher('{graph_name}', $$ {cypher} $$) AS (id agtype)"
        )
        row = await result.fetchone()
        await conn.execute("COMMIT")
        edge_id = str(row["id"]) if row else ""
        return edge_id

    async def query_neighbors(
        self,
        graph_name: str,
        node_id: str,
        edge_labels: list[str] | None = None,
        max_depth: int = 1,
    ) -> list[GraphNode]:
        conn = await self._get_conn()
        # Use variable-length path for depth > 1
        edge_filter = ""
        if edge_labels:
            edge_filter = ":" + "|".join(edge_labels)
        cypher = (
            f"MATCH (a)-[{edge_filter}*1..{max_depth}]->(b) "
            f"WHERE id(a) = {node_id} "
            "RETURN DISTINCT b"
        )
        result = await conn.execute(
            f"SELECT * FROM ag_catalog.cypher('{graph_name}', $$ {cypher} $$) AS (node agtype)"
        )
        nodes: list[GraphNode] = []
        async for row in result:
            node_data = json.loads(str(row["node"]))
            nodes.append(GraphNode(
                id=str(node_data.get("id", "")),
                label=node_data.get("label", ""),
                node_type=node_data.get("label", ""),
                properties=node_data.get("properties", {}),
            ))
        return nodes

    async def query_path(
        self,
        graph_name: str,
        from_id: str,
        to_id: str,
    ) -> list[GraphPath]:
        # Simplified: return shortest path
        conn = await self._get_conn()
        cypher = (
            f"MATCH p = shortestPath((a)-[*..10]->(b)) "
            f"WHERE id(a) = {from_id} AND id(b) = {to_id} "
            "RETURN p"
        )
        try:
            result = await conn.execute(
                f"SELECT * FROM ag_catalog.cypher('{graph_name}', $$ {cypher} $$) AS (path agtype)"
            )
            paths: list[GraphPath] = []
            async for _row in result:
                paths.append(GraphPath(length=1))  # Simplified
            return paths
        except Exception:
            return []

    async def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            await self._conn.close()
            self._conn = None
