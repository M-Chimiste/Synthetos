"""Pilot runner: create a charter + cycle from a fixture and seed discovery.

The runner creates the durable pilot records and enqueues the first discovery
job so the worker can pick up the full chain asynchronously. Its job is to:

  1. Validate the fixture contract.
  2. Insert a ``ResearchCharter`` keyed by ``pilot:<problem_id>`` so repeated
     runs deterministically share the same charter (pilot fixtures are
     idempotent by design).
  3. Insert a new ``ResearchCycle`` with the fixture's autonomy config +
     seeds embedded in ``config``.
  4. Start discovery on the new cycle so the worker has a real pending job.
  5. Return the resulting charter_id + cycle_id so the caller can watch the
     event stream or query artifacts.

Evaluation of a completed pilot run lives in ``libs.pilot.evaluation``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import AutonomyEvents, GoalEvents
from libs.core.events import emit_event_sync
from libs.core.services.discovery_service import start_discovery_session_for_cycle
from libs.core.types import ActorType, CharterStatus, CycleStatus, GoalStatus
from libs.pilot.fixture import PilotFixture
from libs.schemas.discovery import DiscoveryBudget, ProblemProfileCreate, RerankPolicy
from libs.storage.base import get_async_session_factory, get_sync_session_factory
from libs.storage.models.goals import GoalAttempt, ResearchGoal
from libs.storage.models.research import ResearchCharter, ResearchCycle

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class PilotRunHandle:
    problem_id: str
    charter_id: UUID
    cycle_id: UUID
    tier: str
    created_at: datetime


def _upsert_charter(db: Session, fixture: PilotFixture) -> ResearchCharter:
    """Find-or-create the charter for this pilot fixture.

    Pilot charters are keyed by title ``pilot:<problem_id>`` so repeated runs
    of the same fixture share one charter (and one pattern-learning history).
    """
    pilot_title = f"pilot:{fixture.problem_id}"
    existing = db.execute(
        select(ResearchCharter).where(ResearchCharter.title == pilot_title)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.source_scope is None and fixture.charter.get("domain"):
            existing.source_scope = {"domain": fixture.charter.get("domain")}
        return existing
    charter = ResearchCharter(
        id=uuid7(),
        title=pilot_title,
        description=fixture.charter.get("description", ""),
        problem_statement=fixture.charter.get("problem_statement", ""),
        source_scope={"domain": fixture.charter.get("domain")},
        status=CharterStatus.active,
    )
    db.add(charter)
    db.flush()
    return charter


def _cycle_config(fixture: PilotFixture) -> dict:
    """Build a cycle.config payload from the fixture."""
    return {
        "autonomy": fixture.autonomy,
        "seeds": fixture.seeds,
        "pilot": {
            "problem_id": fixture.problem_id,
            "tier": fixture.tier,
            "domain": fixture.charter.get("domain"),
            "success_criteria": fixture.charter.get("success_criteria", []),
            "expected": fixture.expected,
        },
    }


def _discovery_profile(fixture: PilotFixture) -> ProblemProfileCreate:
    """Build the initial discovery problem profile for a pilot cycle."""
    charter = fixture.charter
    reference_sources = fixture.expected.get("reference_sources", []) or []
    derived_query = " ".join(str(item).strip() for item in reference_sources if str(item).strip())
    search_hints = {
        "categories": [],
        "synonyms": [str(charter.get("domain", "")).strip()],
    }
    if derived_query:
        search_hints["derived_query"] = derived_query
    return ProblemProfileCreate(
        query_text=str(charter.get("problem_statement", "")).strip()
        or str(charter.get("title", "")).strip(),
        notes=str(charter.get("description", "")).strip(),
        source_scope={
            "internal_corpus": True,
            "arxiv_live": True,
            "domain": charter.get("domain"),
            "search_hints": search_hints,
        },
        view_preference="both",
        rerank_policy=RerankPolicy(enabled=True),
        budget=DiscoveryBudget(),
    )


def _goal_success_criteria(fixture: PilotFixture) -> list[dict[str, Any]]:
    """Translate the pilot's human fixture contract into goal criteria."""
    criteria: list[dict[str, Any]] = [
        {
            "name": "completed_run",
            "description": "At least one experiment run completed.",
            "required": True,
            "check_type": "completed_run_exists",
            "params": {},
            "scope": "cumulative",
        },
        {
            "name": "verification_passed_or_inconclusive",
            "description": "At least one run reached a non-failed verification verdict.",
            "required": True,
            "check_type": "verification_passed",
            "params": {"accepted_verdicts": ["passed", "inconclusive"]},
            "scope": "cumulative",
        },
    ]

    reference_metrics = fixture.expected.get("reference_metrics") or {}
    if isinstance(reference_metrics, dict):
        for metric_name, threshold in sorted(reference_metrics.items()):
            metric = str(metric_name).strip()
            if not metric:
                continue
            if isinstance(threshold, int | float):
                criteria.append(
                    {
                        "name": f"metric_threshold:{metric}",
                        "description": f"{metric} reaches the fixture threshold.",
                        "required": True,
                        "check_type": "metric_threshold",
                        "params": {
                            "metric": metric,
                            "operator": ">=",
                            "value": threshold,
                        },
                        "scope": "cumulative",
                    }
                )
            else:
                criteria.append(
                    {
                        "name": f"metric_present:{metric}",
                        "description": f"{metric} is present in run metrics.",
                        "required": True,
                        "check_type": "metric_present",
                        "params": {"metric": metric},
                        "scope": "cumulative",
                    }
                )

    required_artifacts = fixture.expected.get("required_artifacts") or []
    if isinstance(required_artifacts, list):
        for raw_artifact in required_artifacts:
            if isinstance(raw_artifact, dict):
                artifact_name = str(
                    raw_artifact.get("name") or raw_artifact.get("path") or ""
                ).strip()
            else:
                artifact_name = str(raw_artifact).strip()
            if not artifact_name:
                continue
            criteria.append(
                {
                    "name": f"artifact:{artifact_name}",
                    "description": f"{artifact_name} exists in the run artifact manifest.",
                    "required": True,
                    "check_type": "artifact_exists",
                    "params": {"artifact_name": artifact_name},
                    "scope": "cumulative",
                }
            )
    return criteria


def _goal_policy(fixture: PilotFixture) -> dict[str, Any]:
    """Build a goal policy that preserves the pilot fixture contract."""
    autonomy = dict(fixture.autonomy or {})
    discovery_profile = _discovery_profile(fixture).model_dump(mode="json")
    return {
        "max_attempt_cycles": int(
            autonomy.get("max_attempt_cycles") or autonomy.get("max_total_runs") or 1
        ),
        "max_total_runs": autonomy.get("max_total_runs"),
        "max_wall_clock_hours": autonomy.get("max_wall_clock_hours"),
        "autonomy": autonomy,
        "discovery": discovery_profile,
        "protocol": dict(autonomy.get("protocol") or {}),
        "pilot": _cycle_config(fixture)["pilot"],
        "seeds": fixture.seeds,
    }


def _attach_goal_to_pilot_cycle(
    db: Session,
    *,
    charter: ResearchCharter,
    cycle: ResearchCycle,
    fixture: PilotFixture,
) -> tuple[ResearchGoal, GoalAttempt]:
    """Create the goal records that let the worker advance a pilot cycle."""
    title = str(fixture.charter.get("title") or fixture.problem_id).strip()
    goal = ResearchGoal(
        id=uuid7(),
        charter_id=charter.id,
        title=f"Pilot: {title}",
        goal_statement=str(fixture.charter.get("problem_statement") or title).strip(),
        success_criteria=_goal_success_criteria(fixture),
        policy=_goal_policy(fixture),
        status=GoalStatus.running.value,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(goal)
    db.flush()

    attempt = GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=charter.id,
        cycle_id=cycle.id,
        attempt_number=1,
        status="running",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(attempt)
    db.flush()

    cycle_config = dict(cycle.config or {})
    cycle_config["goal"] = {
        "goal_id": str(goal.id),
        "attempt_number": 1,
        "goal_statement": goal.goal_statement,
        "success_criteria": goal.success_criteria,
        "prior_attempt_summary": None,
    }
    cycle.config = cycle_config
    cycle.updated_at = utcnow()

    emit_event_sync(
        db,
        event_type=GoalEvents.created.value,
        charter_id=goal.charter_id,
        cycle_id=None,
        payload={
            "goal_id": str(goal.id),
            "title": goal.title,
            "source": "pilot",
            "problem_id": fixture.problem_id,
        },
        actor_type=ActorType.system,
    )
    emit_event_sync(
        db,
        event_type=GoalEvents.attempt_started.value,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={
            "goal_id": str(goal.id),
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "source": "pilot",
        },
        actor_type=ActorType.system,
    )
    return goal, attempt


async def _kickoff_discovery(
    *,
    charter_id: UUID,
    cycle_id: UUID,
    fixture: PilotFixture,
) -> UUID:
    """Seed the discovery chain so the worker has real work to claim."""
    factory = get_async_session_factory()
    async with factory() as db:
        _session, _profile, job_id = await start_discovery_session_for_cycle(
            db,
            charter_id=charter_id,
            cycle_id=cycle_id,
            body=_discovery_profile(fixture),
        )
        await db.commit()
        return job_id


def start_pilot(fixture: PilotFixture) -> PilotRunHandle:
    """Create a charter + cycle for the given fixture and return a handle.

    Commits the transaction before returning so a watching worker can pick
    up any initial jobs the caller might enqueue next.
    """
    factory = get_sync_session_factory()
    with factory() as db:
        charter = _upsert_charter(db, fixture)
        cycle = ResearchCycle(
            id=uuid7(),
            charter_id=charter.id,
            status=CycleStatus.created,
            config=_cycle_config(fixture),
        )
        db.add(cycle)
        db.flush()
        goal, attempt = _attach_goal_to_pilot_cycle(
            db,
            charter=charter,
            cycle=cycle,
            fixture=fixture,
        )

        emit_event_sync(
            db,
            event_type="pilot.cycle_started",
            charter_id=charter.id,
            cycle_id=cycle.id,
            payload={
                "problem_id": fixture.problem_id,
                "tier": fixture.tier,
                "autonomy_mode": fixture.autonomy.get("mode"),
                "max_total_runs": fixture.autonomy.get("max_total_runs"),
                "goal_id": str(goal.id),
                "attempt_id": str(attempt.id),
            },
        )
        # If the fixture's autonomy mode is autonomous, also emit the
        # canonical loop_started event so downstream dashboards group it.
        if fixture.autonomy.get("mode") == "autonomous":
            emit_event_sync(
                db,
                event_type=AutonomyEvents.loop_started.value,
                charter_id=charter.id,
                cycle_id=cycle.id,
                payload={"source": "pilot", "problem_id": fixture.problem_id},
            )

        db.commit()
        handle = PilotRunHandle(
            problem_id=fixture.problem_id,
            charter_id=charter.id,
            cycle_id=cycle.id,
            tier=fixture.tier,
            created_at=utcnow(),
        )
    asyncio.run(
        _kickoff_discovery(
            charter_id=handle.charter_id,
            cycle_id=handle.cycle_id,
            fixture=fixture,
        )
    )
    return handle
