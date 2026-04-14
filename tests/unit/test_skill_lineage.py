"""Skill and model lineage helper tests."""

from __future__ import annotations

from datetime import UTC, datetime

from uuid_utils import uuid7

from libs.core.types import TrustTier
from libs.schemas.model_gateway import CompletionResponse
from libs.skills import lineage
from libs.storage.models.skills import SkillDefinition


class _FakeExecuteResult:
    def __init__(self, skill_def):
        self._skill_def = skill_def

    def scalar_one_or_none(self):
        return self._skill_def


class _FakeSession:
    def __init__(self, skill_def):
        self.skill_def = skill_def
        self.added = []

    def execute(self, _query):
        return _FakeExecuteResult(self.skill_def)

    def add(self, obj):
        self.added.append(obj)

    def get(self, _model, _key):
        # No cycle row in the fake session -- enforcement falls back to
        # cycle_config={} which still allows first-party skills.
        return None


def test_record_skill_usage_creates_binding() -> None:
    skill_def = SkillDefinition(
        id=uuid7(),
        skill_id="ideation.hypothesis_generation",
        version="0.1.0",
        phase="phase3",
        trust_tier=TrustTier.first_party_trusted,
        manifest={},
        body="skill body",
        content_hash=None,
        enabled=True,
        source_path=None,
        discovered_at=datetime.now(UTC),
    )
    session = _FakeSession(skill_def)

    binding_id = lineage.record_skill_usage(
        session,
        skill_id=skill_def.skill_id,
        cycle_id=uuid7(),
        operator_type="hypothesis_generate",
        job_id=uuid7(),
    )

    assert binding_id is not None
    assert session.added[0].skill_def_id == skill_def.id


def test_record_model_call_accepts_structured_or_manual_metadata() -> None:
    session = _FakeSession(None)
    response = CompletionResponse(
        content="ok",
        provider="anthropic",
        model="claude",
        input_tokens=10,
        output_tokens=20,
    )

    lineage.record_model_call(
        session,
        cycle_id=uuid7(),
        job_id=uuid7(),
        role="hypothesis_generation",
        response=response,
    )
    lineage.record_model_call(
        session,
        cycle_id=uuid7(),
        job_id=uuid7(),
        role="protocol_drafting",
        provider="anthropic",
        model_id="claude",
    )

    assert len(session.added) == 2
    assert session.added[0].provider == "anthropic"
    assert session.added[1].model_id == "claude"
