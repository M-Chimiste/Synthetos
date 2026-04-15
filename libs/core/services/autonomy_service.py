"""Async business logic helpers for the Phase 5 autonomy API."""

from __future__ import annotations

from uuid import UUID

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.config import get_settings
from libs.schemas.autonomy import AutonomyReportResponse


async def read_report_file(
    session: AsyncSession,
    cycle_id: UUID,
) -> AutonomyReportResponse:
    """Read the on-disk autonomy completion report bundle for a cycle."""
    settings = get_settings()
    root = settings.data_root / "reports" / "cycles" / str(cycle_id) / "completion"
    md_path = root / "report.md"
    json_path = root / "report.json"

    markdown: str | None = None
    json_payload: dict | None = None

    if md_path.exists():
        markdown = md_path.read_text(encoding="utf-8")
    if json_path.exists():
        try:
            json_payload = orjson.loads(json_path.read_bytes())
        except orjson.JSONDecodeError:
            json_payload = None

    return AutonomyReportResponse(
        cycle_id=UUID(str(cycle_id)),
        markdown=markdown,
        json=json_payload,
    )
