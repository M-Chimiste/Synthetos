"""Skill catalog API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db, get_settings
from libs.core.config import Settings
from libs.schemas.common import PaginatedResponse
from libs.schemas.skills import SkillDefinitionRead
from libs.skills.loader import discover_skills
from libs.skills.registry import get_skill, list_skills, upsert_skill

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=PaginatedResponse[SkillDefinitionRead])
async def list_skills_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    enabled_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    skills, total = await list_skills(db, enabled_only=enabled_only, offset=offset, limit=limit)
    return PaginatedResponse(items=skills, total=total, offset=offset, limit=limit)


@router.get("/{skill_id:path}", response_model=SkillDefinitionRead)
async def get_skill_endpoint(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    skill = await get_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return skill


@router.post("/discover", response_model=list[SkillDefinitionRead])
async def discover_skills_endpoint(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Scan configured skill paths and upsert discovered skills."""
    search_paths = settings.skill_path_list
    first_party_root = Path("skills")

    discovered = discover_skills(search_paths, first_party_root=first_party_root)

    results = []
    for skill in discovered:
        defn = await upsert_skill(db, skill)
        results.append(defn)

    await db.commit()
    return results
