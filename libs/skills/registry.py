"""Persist and query skill definitions in the database."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.schemas.skills import SkillDefinitionRead
from libs.skills.loader import DiscoveredSkill
from libs.storage.models.skills import SkillDefinition


async def upsert_skill(
    session: AsyncSession, skill: DiscoveredSkill
) -> SkillDefinitionRead:
    """Insert or update a skill definition from a discovered skill."""
    result = await session.execute(
        select(SkillDefinition).where(
            SkillDefinition.skill_id == skill.manifest.id
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.version = skill.manifest.version
        existing.phase = skill.manifest.phase
        existing.trust_tier = skill.trust_tier
        existing.manifest = skill.manifest.model_dump()
        existing.body = skill.body
        existing.content_hash = skill.content_hash
        existing.source_path = str(skill.source_path)
        existing.discovered_at = utcnow()
        await session.flush()
        return SkillDefinitionRead.model_validate(existing)

    defn = SkillDefinition(
        id=uuid7(),
        skill_id=skill.manifest.id,
        version=skill.manifest.version,
        phase=skill.manifest.phase,
        trust_tier=skill.trust_tier,
        manifest=skill.manifest.model_dump(),
        body=skill.body,
        content_hash=skill.content_hash,
        enabled=True,
        source_path=str(skill.source_path),
        discovered_at=utcnow(),
    )
    session.add(defn)
    await session.flush()
    return SkillDefinitionRead.model_validate(defn)


async def list_skills(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[SkillDefinitionRead], int]:
    """List skill definitions with optional filters."""
    query = select(SkillDefinition)
    if enabled_only:
        query = query.where(SkillDefinition.enabled.is_(True))

    count_result = await session.execute(select(SkillDefinition.id))
    total = len(count_result.all())

    result = await session.execute(
        query.order_by(SkillDefinition.skill_id).offset(offset).limit(limit)
    )
    skills = [SkillDefinitionRead.model_validate(s) for s in result.scalars().all()]
    return skills, total


async def get_skill(
    session: AsyncSession, skill_id: str
) -> SkillDefinitionRead | None:
    """Fetch a skill definition by its skill_id string."""
    result = await session.execute(
        select(SkillDefinition).where(SkillDefinition.skill_id == skill_id)
    )
    defn = result.scalar_one_or_none()
    if defn is None:
        return None
    return SkillDefinitionRead.model_validate(defn)
