"""Goal-oriented research services."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import GoalEvents
from libs.core.events import emit_event_sync
from libs.core.services.job_service import create_job
from libs.core.services.result_introspection import (
    build_goal_result_summary,
    render_goal_result_markdown,
)
from libs.core.types import ActorType, CycleStatus, GoalStatus, JobStatus
from libs.schemas.analysis import AnalysisBudget
from libs.schemas.experiment import HypothesisBudget
from libs.schemas.goals import GoalCreate, GoalPolicy, GoalRepairPlan
from libs.schemas.model_gateway import ModelRole
from libs.storage.models.analysis import AnalysisSession
from libs.storage.models.discovery import DiscoverySession, ProblemProfile
from libs.storage.models.experiment import (
    ExperimentSpec,
    HypothesisCard,
    HypothesisSession,
    RunRecord,
    VerificationReport,
)
from libs.storage.models.goals import GoalAttempt, ResearchGoal
from libs.storage.models.jobs import Job
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCharter, ResearchCycle
from libs.verification.contracts import expected_artifact_name

_DEFAULT_SOURCE_SCOPE = {
    "internal_corpus": True,
    "arxiv_live": True,
    "search_hints": {"categories": [], "synonyms": []},
}


class GoalServiceError(Exception):
    """Raised when a goal operation cannot proceed."""


_ACTIVE_JOB_STATUSES = (
    JobStatus.pending.value,
    JobStatus.claimed.value,
    JobStatus.running.value,
    JobStatus.paused.value,
)


def _goal_report_root(goal_id: UUID) -> Path:
    return Path(get_settings().data_root) / "reports" / "goals" / str(goal_id)


def goal_status_paths(goal_id: UUID) -> dict[str, str]:
    root = _goal_report_root(goal_id)
    return {
        "json": str(root / "status.json"),
        "markdown": str(root / "status.md"),
    }


def read_goal_status_ledger(goal_id: UUID) -> dict[str, Any]:
    paths = goal_status_paths(goal_id)
    json_path = Path(paths["json"])
    if not json_path.exists():
        return {"goal_id": str(goal_id), "entries": []}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"goal_id": str(goal_id), "entries": []}
    if not isinstance(payload, dict):
        return {"goal_id": str(goal_id), "entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    payload.setdefault("goal_id", str(goal_id))
    return payload


def latest_goal_status_summary(goal_id: UUID) -> dict[str, Any] | None:
    entries = read_goal_status_ledger(goal_id).get("entries") or []
    if not entries:
        return None
    entry = dict(entries[-1])
    return {
        "kind": entry.get("kind"),
        "stage": entry.get("stage"),
        "summary": entry.get("summary"),
        "outcome": entry.get("outcome"),
        "created_at": entry.get("created_at"),
    }


def append_goal_ledger_entry(
    session,
    goal: ResearchGoal,
    attempt: GoalAttempt | None,
    *,
    kind: str,
    stage: str,
    summary: str,
    outcome: str | None = None,
    fingerprint: str | None = None,
    detail: dict[str, Any] | None = None,
    repair_plan: dict[str, Any] | None = None,
    cycle_id: UUID | None = None,
    actor_type: ActorType = ActorType.worker,
) -> dict[str, Any]:
    """Append one status-ledger entry and render JSON/Markdown artifacts."""
    root = _goal_report_root(goal.id)
    root.mkdir(parents=True, exist_ok=True)
    paths = goal_status_paths(goal.id)
    ledger = read_goal_status_ledger(goal.id)
    entry = {
        "id": str(uuid7()),
        "goal_id": str(goal.id),
        "attempt_id": str(attempt.id) if attempt else None,
        "attempt_number": attempt.attempt_number if attempt else None,
        "cycle_id": str(cycle_id or (attempt.cycle_id if attempt else "")) or None,
        "kind": kind,
        "stage": stage,
        "summary": summary,
        "outcome": outcome,
        "fingerprint": fingerprint,
        "detail": detail or {},
        "repair_plan": repair_plan,
        "created_at": utcnow().isoformat(),
    }
    ledger.setdefault("entries", []).append(entry)
    Path(paths["json"]).write_text(
        json.dumps(ledger, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    Path(paths["markdown"]).write_text(_render_status_markdown(ledger), encoding="utf-8")

    if attempt is not None:
        evaluation = dict(attempt.evaluation or {})
        evaluation["status_ledger"] = {
            "json_path": paths["json"],
            "markdown_path": paths["markdown"],
            "latest": latest_goal_status_summary(goal.id),
        }
        attempt.evaluation = evaluation
        attempt.updated_at = utcnow()

    emit_event_sync(
        session,
        event_type=GoalEvents.ledger_updated.value,
        charter_id=goal.charter_id,
        cycle_id=cycle_id or (attempt.cycle_id if attempt else None),
        payload={
            "goal_id": str(goal.id),
            "attempt_id": str(attempt.id) if attempt else None,
            "kind": kind,
            "stage": stage,
            "summary": summary,
            "status_json_path": paths["json"],
            "status_markdown_path": paths["markdown"],
        },
        actor_type=actor_type,
    )
    return entry


def _render_status_markdown(ledger: dict[str, Any]) -> str:
    lines = [
        f"# Goal Status Ledger: {ledger.get('goal_id', 'unknown')}",
        "",
        "This ledger is append-only. Each entry records what the agent tried, "
        "why it changed course, and the retry fingerprint used to avoid loops.",
        "",
    ]
    entries = ledger.get("entries") or []
    if not entries:
        lines.append("No status entries have been recorded yet.")
        return "\n".join(lines) + "\n"

    for entry in entries:
        lines.extend(
            [
                f"## {entry.get('created_at', '')} - {entry.get('kind', 'entry')}",
                "",
                f"- **Attempt:** {entry.get('attempt_number') or 'n/a'}",
                f"- **Stage:** {entry.get('stage') or 'n/a'}",
                f"- **Outcome:** {entry.get('outcome') or 'n/a'}",
                f"- **Summary:** {entry.get('summary') or ''}",
            ]
        )
        if entry.get("fingerprint"):
            lines.append(f"- **Fingerprint:** `{entry['fingerprint']}`")
        plan = entry.get("repair_plan") or {}
        if plan:
            lines.extend(
                [
                    f"- **Repair action:** {plan.get('proposed_action') or 'n/a'}",
                    f"- **Change:** {plan.get('change_summary') or ''}",
                    f"- **Anti-repeat reason:** {plan.get('anti_repeat_reason') or ''}",
                ]
            )
        detail = entry.get("detail") or {}
        if detail:
            lines.extend(["", "```json", json.dumps(detail, indent=2, sort_keys=True), "```"])
        lines.append("")
    return "\n".join(lines)


def retry_fingerprint(
    *,
    stage: str,
    selected_paper_id: str | None,
    config_patch: dict[str, Any] | None,
    error_class: str,
    proposed_action: str,
) -> str:
    payload = {
        "stage": stage,
        "selected_paper_id": selected_paper_id,
        "config_patch": config_patch or {},
        "error_class": error_class,
        "proposed_action": proposed_action,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _ledger_has_failed_fingerprint(goal_id: UUID, fingerprint: str) -> bool:
    for entry in read_goal_status_ledger(goal_id).get("entries") or []:
        if entry.get("fingerprint") == fingerprint and entry.get("outcome") in {
            "failed",
            "retry_started",
            "duplicate_rejected",
            "blocked",
        }:
            return True
    return False


def _ledger_has_failed_job(goal_id: UUID, job_id: str | None) -> bool:
    if not job_id:
        return False
    for entry in read_goal_status_ledger(goal_id).get("entries") or []:
        detail = entry.get("detail") or {}
        if str(detail.get("failed_job_id") or "") == job_id and entry.get("kind") == "failure":
            return True
    return False


def create_goal_sync(
    session,
    data: GoalCreate,
    *,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> ResearchGoal:
    """Create a goal and seed its first cycle attempt."""
    charter = session.get(ResearchCharter, data.charter_id)
    if charter is None:
        raise GoalServiceError(f"charter {data.charter_id} not found")

    policy = data.policy.model_dump()
    if not policy.get("autonomy"):
        policy["autonomy"] = {"mode": "autonomous", "max_total_runs": 4}

    goal = ResearchGoal(
        id=uuid7(),
        charter_id=data.charter_id,
        title=data.title,
        goal_statement=data.goal_statement,
        success_criteria=[c.model_dump() for c in data.success_criteria],
        policy=policy,
        status=GoalStatus.running.value,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(goal)
    session.flush()

    emit_event_sync(
        session,
        event_type=GoalEvents.created.value,
        charter_id=goal.charter_id,
        cycle_id=None,
        payload={"goal_id": str(goal.id), "title": goal.title},
        actor_type=actor_type,
        actor_id=actor_id,
    )
    start_goal_attempt_sync(session, goal, actor_type=actor_type, actor_id=actor_id)
    return goal


def start_goal_attempt_sync(
    session,
    goal: ResearchGoal,
    *,
    prior_attempt_summary: str | None = None,
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> GoalAttempt:
    """Create and kick off a new cycle attempt for a goal."""
    max_attempt = session.execute(
        select(func.coalesce(func.max(GoalAttempt.attempt_number), 0)).where(
            GoalAttempt.goal_id == goal.id
        )
    ).scalar_one()
    attempt_number = int(max_attempt) + 1
    policy = GoalPolicy.model_validate(goal.policy or {})
    autonomy = dict(policy.autonomy or {})
    if not autonomy:
        autonomy = {"mode": "autonomous", "max_total_runs": 4}

    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=goal.charter_id,
        status=CycleStatus.created,
        config={
            "autonomy": autonomy,
            "goal": {
                "goal_id": str(goal.id),
                "attempt_number": attempt_number,
                "goal_statement": goal.goal_statement,
                "success_criteria": goal.success_criteria,
                "prior_attempt_summary": prior_attempt_summary,
            },
        },
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(cycle)
    session.flush()

    attempt = GoalAttempt(
        id=uuid7(),
        goal_id=goal.id,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        attempt_number=attempt_number,
        status="running",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(attempt)
    session.flush()

    _start_discovery_for_goal_cycle(session, goal, cycle, attempt, policy.discovery)

    emit_event_sync(
        session,
        event_type=GoalEvents.attempt_started.value,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={
            "goal_id": str(goal.id),
            "attempt_id": str(attempt.id),
            "attempt_number": attempt_number,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    return attempt


def _start_discovery_for_goal_cycle(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
    discovery: dict[str, Any] | None,
) -> None:
    cfg = dict(discovery or {})
    source_scope = dict(cfg.get("source_scope") or _DEFAULT_SOURCE_SCOPE)
    profile = ProblemProfile(
        id=uuid7(),
        cycle_id=cycle.id,
        query_text=str(cfg.get("query_text") or goal.goal_statement),
        notes=str(cfg.get("notes") or f"Goal attempt {attempt.attempt_number}: {goal.title}"),
        source_scope=source_scope,
        view_preference=str(cfg.get("view_preference") or "both"),
        rerank_policy=cfg.get("rerank_policy") or {"enabled": True},
        budget=cfg.get("budget") or {},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(profile)
    session.flush()

    discovery_session = DiscoverySession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=goal.charter_id,
        profile_id=profile.id,
        status="created",
        view=profile.view_preference,
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(discovery_session)
    session.flush()

    create_job(
        session,
        cycle_id=cycle.id,
        job_type="discovery_intake",
        payload={"session_id": str(discovery_session.id)},
        priority=10,
    )


def enqueue_goal_advance_sync(
    session,
    *,
    cycle_id: UUID,
    goal_id: UUID | str | None = None,
    trigger: str,
    failure: dict[str, Any] | None = None,
    priority: int = 9,
) -> Job | None:
    """Queue a goal advancement job unless one is already active for the cycle."""
    cycle = session.get(ResearchCycle, cycle_id)
    if cycle is None:
        return None
    goal_cfg = (cycle.config or {}).get("goal") or {}
    resolved_goal_id = str(goal_id or goal_cfg.get("goal_id") or "")
    if not resolved_goal_id:
        return None

    existing = session.execute(
        select(Job)
        .where(Job.cycle_id == cycle_id)
        .where(Job.job_type == "goal_advance")
        .where(Job.status.in_(_ACTIVE_JOB_STATUSES))
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return None

    return create_job(
        session,
        cycle_id=cycle_id,
        job_type="goal_advance",
        payload={
            "goal_id": resolved_goal_id,
            "cycle_id": str(cycle_id),
            "trigger": trigger,
            "failure": failure,
        },
        priority=priority,
    )


def advance_goal_cycle_sync(
    session,
    *,
    goal_id: UUID,
    cycle_id: UUID,
    trigger: str,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance a goal-linked cycle by observing its current state."""
    goal = session.get(ResearchGoal, goal_id)
    if goal is None:
        raise GoalServiceError(f"goal {goal_id} not found")
    cycle = session.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise GoalServiceError(f"cycle {cycle_id} not found")

    attempt = _attempt_for_cycle(session, goal_id, cycle_id)
    if attempt is None:
        raise GoalServiceError(f"goal attempt for cycle {cycle_id} not found")

    if goal.status in {
        GoalStatus.satisfied.value,
        GoalStatus.exhausted.value,
        GoalStatus.stopped.value,
        GoalStatus.failed.value,
    }:
        return {"next_action": "goal_inactive", "summary": f"goal is {goal.status}"}

    emit_event_sync(
        session,
        event_type=GoalEvents.advance_started.value,
        charter_id=goal.charter_id,
        cycle_id=cycle_id,
        payload={"goal_id": str(goal.id), "trigger": trigger},
        actor_type=ActorType.worker,
    )

    if failure:
        return _handle_goal_pre_run_failure(
            session,
            goal=goal,
            cycle=cycle,
            attempt=attempt,
            failure=failure,
        )

    status = str(cycle.status)
    if status == CycleStatus.discovery_screened.value:
        result = _advance_from_discovery(session, goal, cycle, attempt)
    elif status == CycleStatus.evidence_ready.value:
        result = _advance_from_evidence(session, goal, cycle, attempt)
    elif status == CycleStatus.portfolio_ready.value:
        result = _advance_from_portfolio(session, goal, cycle, attempt)
    elif status == CycleStatus.protocol_ready.value:
        result = _advance_from_protocol_ready(session, goal, cycle, attempt)
    else:
        result = {"next_action": "noop", "summary": f"cycle status {status} is owned elsewhere"}

    append_goal_ledger_entry(
        session,
        goal,
        attempt,
        kind="advance",
        stage=_stage_for_status(status),
        summary=result["summary"],
        outcome=result["next_action"],
        detail={"trigger": trigger, "cycle_status": status},
        cycle_id=cycle.id,
    )
    emit_event_sync(
        session,
        event_type=GoalEvents.advance_completed.value,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={"goal_id": str(goal.id), **result},
        actor_type=ActorType.worker,
    )
    return result


def _attempt_for_cycle(session, goal_id: UUID, cycle_id: UUID) -> GoalAttempt | None:
    return session.execute(
        select(GoalAttempt).where(
            GoalAttempt.goal_id == goal_id,
            GoalAttempt.cycle_id == cycle_id,
        )
    ).scalar_one_or_none()


def _stage_for_status(status: str) -> str:
    if status == CycleStatus.discovery_screened.value:
        return "analysis"
    if status == CycleStatus.evidence_ready.value:
        return "hypothesis"
    if status == CycleStatus.portfolio_ready.value:
        return "protocol"
    if status == CycleStatus.protocol_ready.value:
        return "execution"
    return status


def _advance_from_discovery(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
) -> dict[str, Any]:
    paper = _select_goal_paper(session, cycle.id)
    if paper is None:
        return _block_or_next_attempt(
            session,
            goal=goal,
            attempt=attempt,
            stage="analysis",
            summary="No shortlisted or escalated paper was available for analysis.",
        )
    existing = _latest_analysis_session(session, cycle.id, paper.id)
    if existing and existing.status not in ("failed", "cancelled"):
        return {
            "next_action": "already_started",
            "summary": f"analysis already exists for paper {paper.id}",
            "analysis_session_id": str(existing.id),
        }

    analysis = _start_analysis_for_goal(session, goal, cycle, paper)
    return {
        "next_action": "analysis_started",
        "summary": f"started analysis for {paper.title}",
        "paper_card_id": str(paper.id),
        "analysis_session_id": str(analysis.id),
    }


def _advance_from_evidence(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
) -> dict[str, Any]:
    existing = session.execute(
        select(HypothesisSession)
        .where(HypothesisSession.cycle_id == cycle.id)
        .where(HypothesisSession.status.notin_(["failed", "cancelled"]))
        .order_by(HypothesisSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "next_action": "already_started",
            "summary": f"hypothesis session already exists: {existing.id}",
            "hypothesis_session_id": str(existing.id),
        }

    hs = _start_hypothesis_for_goal(session, goal, cycle)
    return {
        "next_action": "hypothesis_started",
        "summary": "started hypothesis generation",
        "hypothesis_session_id": str(hs.id),
    }


def _advance_from_portfolio(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
) -> dict[str, Any]:
    hs = _latest_completed_hypothesis_session(session, cycle.id)
    if hs is None:
        return _block_or_next_attempt(
            session,
            goal=goal,
            attempt=attempt,
            stage="protocol",
            summary="No completed hypothesis session was available for compilation.",
        )
    card = _top_hypothesis_card(session, hs.id)
    if card is None:
        return _block_or_next_attempt(
            session,
            goal=goal,
            attempt=attempt,
            stage="protocol",
            summary="No ranked hypothesis card was available for compilation.",
        )
    existing = session.execute(
        select(Job)
        .where(Job.cycle_id == cycle.id)
        .where(Job.job_type == "protocol_compile")
        .where(Job.status.in_(_ACTIVE_JOB_STATUSES))
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "next_action": "already_started",
            "summary": f"protocol compile job already active: {existing.id}",
            "job_id": str(existing.id),
        }

    policy = GoalPolicy.model_validate(goal.policy or {})
    protocol_cfg = dict(policy.protocol or {})
    payload: dict[str, Any] = {
        "hypothesis_session_id": str(hs.id),
        "hypothesis_card_ids": [str(card.id)],
        "from_loop": True,
        "loop_context": {
            "source": "goal",
            "goal_id": str(goal.id),
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
        },
    }
    if protocol_cfg.get("hardware_profile"):
        payload["hardware_profile"] = protocol_cfg["hardware_profile"]
    if protocol_cfg.get("base_image"):
        payload["base_image"] = protocol_cfg["base_image"]
    job = create_job(
        session,
        cycle_id=cycle.id,
        job_type="protocol_compile",
        payload=payload,
        priority=10,
    )
    return {
        "next_action": "protocol_compile_started",
        "summary": f"compiling top hypothesis: {card.title}",
        "job_id": str(job.id),
        "hypothesis_card_id": str(card.id),
    }


def _advance_from_protocol_ready(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
) -> dict[str, Any]:
    # Fallback for goal-linked cycles where a compile produced specs without
    # from_loop. Start execution from the latest validated spec.
    run_count = session.execute(
        select(func.count()).select_from(RunRecord).where(RunRecord.cycle_id == cycle.id)
    ).scalar_one()
    if run_count:
        return {"next_action": "noop", "summary": "run already exists"}
    spec = session.execute(
        select(ExperimentSpec)
        .where(ExperimentSpec.cycle_id == cycle.id)
        .where(ExperimentSpec.status == "validated")
        .order_by(ExperimentSpec.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if spec is None:
        return _block_or_next_attempt(
            session,
            goal=goal,
            attempt=attempt,
            stage="execution",
            summary="No validated experiment spec was available for execution.",
        )
    run_number = session.execute(
        select(func.coalesce(func.max(RunRecord.run_number), 0)).where(
            RunRecord.experiment_spec_id == spec.id
        )
    ).scalar_one()
    run = RunRecord(
        id=uuid7(),
        experiment_spec_id=spec.id,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        run_number=int(run_number) + 1,
        status="pending",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(run)
    session.flush()
    create_job(
        session,
        cycle_id=cycle.id,
        job_type="execution_setup",
        payload={"run_record_id": str(run.id)},
        priority=10,
    )
    cycle.status = CycleStatus.running
    cycle.updated_at = utcnow()
    return {
        "next_action": "execution_started",
        "summary": f"started execution for spec {spec.id}",
        "run_record_id": str(run.id),
    }


def _select_goal_paper(session, cycle_id: UUID) -> PaperCard | None:
    sessions = select(DiscoverySession.id).where(DiscoverySession.cycle_id == cycle_id)
    return session.execute(
        select(PaperCard)
        .where(PaperCard.session_id.in_(sessions))
        .where(PaperCard.triage_status.in_(["shortlisted", "escalated"]))
        .order_by(PaperCard.final_score.desc().nulls_last(), PaperCard.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_analysis_session(
    session,
    cycle_id: UUID,
    paper_card_id: UUID,
) -> AnalysisSession | None:
    return session.execute(
        select(AnalysisSession)
        .where(AnalysisSession.cycle_id == cycle_id)
        .where(AnalysisSession.paper_card_id == paper_card_id)
        .order_by(AnalysisSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _start_analysis_for_goal(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    paper: PaperCard,
    *,
    config_patch: dict[str, Any] | None = None,
) -> AnalysisSession:
    policy = GoalPolicy.model_validate(goal.policy or {})
    budget_cfg = dict(policy.analysis or {})
    budget_cfg.update(config_patch or {})
    budget = AnalysisBudget.model_validate(budget_cfg or {}).model_dump()
    if str(cycle.status) in (
        CycleStatus.discovery_screened.value,
        CycleStatus.analysis_ready.value,
    ):
        cycle.status = CycleStatus.analysis_ready
        cycle.updated_at = utcnow()

    analysis = AnalysisSession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=goal.charter_id,
        paper_card_id=paper.id,
        status="created",
        budget=budget,
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(analysis)
    session.flush()
    create_job(
        session,
        cycle_id=cycle.id,
        job_type="analysis_ingest",
        payload={"analysis_session_id": str(analysis.id)},
        priority=10,
    )
    emit_event_sync(
        session,
        event_type="analysis.session_started",
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={
            "analysis_session_id": str(analysis.id),
            "paper_card_id": str(paper.id),
            "source": "goal",
        },
        actor_type=ActorType.worker,
    )
    return analysis


def _start_hypothesis_for_goal(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    *,
    config_patch: dict[str, Any] | None = None,
) -> HypothesisSession:
    policy = GoalPolicy.model_validate(goal.policy or {})
    budget_cfg = dict(policy.hypothesis or {})
    budget_cfg.update(config_patch or {})
    budget = HypothesisBudget.model_validate(budget_cfg or {}).model_dump()
    hs = HypothesisSession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=goal.charter_id,
        status="created",
        budget=budget,
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(hs)
    session.flush()
    create_job(
        session,
        cycle_id=cycle.id,
        job_type="hypothesis_generate",
        payload={"hypothesis_session_id": str(hs.id)},
        priority=10,
    )
    emit_event_sync(
        session,
        event_type="ideation.session_started",
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={"hypothesis_session_id": str(hs.id), "source": "goal"},
        actor_type=ActorType.worker,
    )
    return hs


def _latest_completed_hypothesis_session(session, cycle_id: UUID) -> HypothesisSession | None:
    return session.execute(
        select(HypothesisSession)
        .where(HypothesisSession.cycle_id == cycle_id)
        .where(HypothesisSession.status == "completed")
        .order_by(HypothesisSession.completed_at.desc().nulls_last())
        .limit(1)
    ).scalar_one_or_none()


def _top_hypothesis_card(session, hypothesis_session_id: UUID) -> HypothesisCard | None:
    return session.execute(
        select(HypothesisCard)
        .where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
        .where(HypothesisCard.status.in_(["candidate", "selected"]))
        .order_by(HypothesisCard.rank.asc().nulls_last(), HypothesisCard.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def _handle_goal_pre_run_failure(
    session,
    *,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
    failure: dict[str, Any],
) -> dict[str, Any]:
    failed_job_id = str(failure.get("failed_job_id") or failure.get("job_id") or "")
    stage = _stage_for_job_type(str(failure.get("job_type") or ""))
    if _ledger_has_failed_job(goal.id, failed_job_id):
        return {"next_action": "already_recorded", "summary": "failure already recorded"}

    selected_paper_id = str(failure.get("paper_card_id") or "") or _latest_cycle_paper_id(
        session, cycle.id
    )
    error_text = str(failure.get("error") or "unknown error")
    error_class = _error_class(error_text)
    failure_fp = retry_fingerprint(
        stage=stage,
        selected_paper_id=selected_paper_id,
        config_patch={"failed_job_payload": failure.get("job_payload") or {}},
        error_class=error_class,
        proposed_action="failure_observed",
    )
    append_goal_ledger_entry(
        session,
        goal,
        attempt,
        kind="failure",
        stage=stage,
        summary=f"{stage} failed: {error_text[:240]}",
        outcome="failed",
        fingerprint=failure_fp,
        detail={
            "failed_job_id": failed_job_id or None,
            "failed_session_id": failure.get("session_id"),
            "failed_job_type": failure.get("job_type"),
            "failed_job_payload": failure.get("job_payload") or {},
            "paper_card_id": selected_paper_id,
            "error": error_text,
            "error_class": error_class,
        },
        cycle_id=cycle.id,
    )

    plan = _build_goal_repair_plan(
        goal=goal,
        attempt=attempt,
        cycle=cycle,
        failure=failure,
        stage=stage,
        error_class=error_class,
        selected_paper_id=selected_paper_id,
    )
    plan_payload = plan.model_dump()
    repair_fp = retry_fingerprint(
        stage=stage,
        selected_paper_id=selected_paper_id,
        config_patch={
            "payload_patch": plan.payload_patch,
            "config_patch": plan.config_patch,
        },
        error_class=error_class,
        proposed_action=plan.proposed_action,
    )

    if _ledger_has_failed_fingerprint(goal.id, repair_fp):
        append_goal_ledger_entry(
            session,
            goal,
            attempt,
            kind="repair",
            stage=stage,
            summary="Rejected duplicate repair plan.",
            outcome="duplicate_rejected",
            fingerprint=repair_fp,
            detail={"error_class": error_class},
            repair_plan=plan_payload,
            cycle_id=cycle.id,
        )
        emit_event_sync(
            session,
            event_type=GoalEvents.retry_rejected_duplicate.value,
            charter_id=goal.charter_id,
            cycle_id=cycle.id,
            payload={"goal_id": str(goal.id), "fingerprint": repair_fp, "stage": stage},
            actor_type=ActorType.worker,
        )
        return _block_or_next_attempt(
            session,
            goal=goal,
            attempt=attempt,
            stage=stage,
            summary="Duplicate repair plan rejected; moving to a new attempt if budget remains.",
            repair_plan=plan_payload,
        )

    emit_event_sync(
        session,
        event_type=GoalEvents.repair_requested.value,
        charter_id=goal.charter_id,
        cycle_id=cycle.id,
        payload={"goal_id": str(goal.id), "stage": stage, "repair_plan": plan_payload},
        actor_type=ActorType.worker,
    )

    if plan.proposed_action == "retry_stage" and _repair_budget_available(
        goal, attempt, stage
    ):
        retry = _apply_stage_retry(
            session,
            goal=goal,
            cycle=cycle,
            attempt=attempt,
            stage=stage,
            failure=failure,
            plan=plan,
        )
        append_goal_ledger_entry(
            session,
            goal,
            attempt,
            kind="repair",
            stage=stage,
            summary=plan.change_summary,
            outcome="retry_started" if retry["started"] else "blocked",
            fingerprint=repair_fp,
            detail={"retry": retry, "expected_new_information": plan.expected_new_information},
            repair_plan=plan_payload,
            cycle_id=cycle.id,
        )
        emit_event_sync(
            session,
            event_type=GoalEvents.repair_applied.value,
            charter_id=goal.charter_id,
            cycle_id=cycle.id,
            payload={"goal_id": str(goal.id), "stage": stage, **retry},
            actor_type=ActorType.worker,
        )
        return {
            "next_action": "retry_started" if retry["started"] else "blocked",
            "summary": retry["summary"],
            "fingerprint": repair_fp,
        }

    if plan.proposed_action == "stop_failed":
        attempt.status = "failed"
        attempt.completed_at = utcnow()
        attempt.updated_at = attempt.completed_at
        goal.status = GoalStatus.failed.value
        goal.completed_at = utcnow()
        goal.updated_at = goal.completed_at
        append_goal_ledger_entry(
            session,
            goal,
            attempt,
            kind="repair",
            stage=stage,
            summary=plan.change_summary,
            outcome="stopped_failed",
            fingerprint=repair_fp,
            repair_plan=plan_payload,
            cycle_id=cycle.id,
        )
        return {"next_action": "failed", "summary": plan.change_summary}

    return _block_or_next_attempt(
        session,
        goal=goal,
        attempt=attempt,
        stage=stage,
        summary=plan.change_summary or "Starting a new attempt with failure context.",
        repair_plan=plan_payload,
        fingerprint=repair_fp,
    )


def _stage_for_job_type(job_type: str) -> str:
    if job_type.startswith("discovery_"):
        return "discovery"
    if job_type.startswith("analysis_"):
        return "analysis"
    if job_type.startswith("hypothesis_"):
        return "hypothesis"
    if job_type.startswith("protocol_"):
        return "protocol"
    return job_type or "unknown"


def _error_class(error: str) -> str:
    lowered = error.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "json" in lowered or "validation" in lowered or "parse" in lowered:
        return "structured_output"
    if "connection" in lowered or "connect" in lowered or "http" in lowered:
        return "service_unavailable"
    if "not found" in lowered or "missing" in lowered:
        return "missing_input"
    return "unknown"


def _latest_cycle_paper_id(session, cycle_id: UUID) -> str | None:
    analysis = session.execute(
        select(AnalysisSession)
        .where(AnalysisSession.cycle_id == cycle_id)
        .order_by(AnalysisSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return str(analysis.paper_card_id) if analysis else None


def _repair_budget_available(goal: ResearchGoal, attempt: GoalAttempt, stage: str) -> bool:
    policy = GoalPolicy.model_validate(goal.policy or {})
    repair_cfg = dict(policy.repair or {})
    max_same_stage = int(repair_cfg.get("max_same_stage_repairs", 1))
    max_total = int(repair_cfg.get("max_pre_run_repairs_per_attempt", 2))
    entries = read_goal_status_ledger(goal.id).get("entries") or []
    applied = [
        e
        for e in entries
        if e.get("attempt_id") == str(attempt.id)
        and e.get("kind") == "repair"
        and e.get("outcome") == "retry_started"
    ]
    if len(applied) >= max_total:
        return False
    same_stage = [e for e in applied if e.get("stage") == stage]
    return len(same_stage) < max_same_stage


def _build_goal_repair_plan(
    *,
    goal: ResearchGoal,
    attempt: GoalAttempt,
    cycle: ResearchCycle,
    failure: dict[str, Any],
    stage: str,
    error_class: str,
    selected_paper_id: str | None,
) -> GoalRepairPlan:
    if not _repair_budget_available(goal, attempt, stage):
        return GoalRepairPlan(
            diagnosis=f"{stage} failed and the same-stage repair budget is exhausted.",
            previous_attempts_considered=_ledger_summaries(goal.id),
            proposed_action="start_next_attempt",
            change_summary="Start a new attempt with the failure context in discovery notes.",
            expected_new_information=(
                "A new attempt can choose a different retrieval or planning path."
            ),
            anti_repeat_reason="Same-stage repair budget prevents repeated identical retries.",
        )
    try:
        return asyncio.run(
            _request_goal_repair_plan(
                goal=goal,
                attempt=attempt,
                cycle=cycle,
                failure=failure,
                stage=stage,
                error_class=error_class,
                selected_paper_id=selected_paper_id,
            )
        )
    except Exception:
        return GoalRepairPlan(
            diagnosis=f"{stage} failed with {error_class}.",
            previous_attempts_considered=_ledger_summaries(goal.id),
            proposed_action="retry_stage",
            change_summary="Retry the failed stage once using a conservative budget patch.",
            expected_new_information=(
                "A fresh stage session may distinguish transient service failure from "
                "deterministic failure."
            ),
            anti_repeat_reason=(
                "The retry uses a fresh session and is fingerprinted against prior failures."
            ),
            config_patch=_fallback_stage_patch(stage, error_class),
        )


async def _request_goal_repair_plan(
    *,
    goal: ResearchGoal,
    attempt: GoalAttempt,
    cycle: ResearchCycle,
    failure: dict[str, Any],
    stage: str,
    error_class: str,
    selected_paper_id: str | None,
) -> GoalRepairPlan:
    ledger = read_goal_status_ledger(goal.id)
    policy = GoalPolicy.model_validate(goal.policy or {})
    allowed_patch_fields = dict(policy.repair or {}).get(
        "allowed_patch_fields",
        {
            "analysis": [
                "max_chunks",
                "graph_extraction_concurrency",
                "evidence_extraction_concurrency",
                "html_quality_threshold",
            ],
            "hypothesis": ["max_hypotheses", "max_critique_rounds"],
            "protocol": ["hardware_profile", "base_image"],
            "discovery": ["budget", "source_scope", "query_text", "notes"],
        },
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are supervising an autonomous AI research goal. "
                "Choose a bounded repair plan that avoids repeating failed work. "
                "Only propose patch fields that are explicitly allowed. "
                "The status ledger is authoritative; cite prior entries you considered."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "goal": {
                        "id": str(goal.id),
                        "title": goal.title,
                        "statement": goal.goal_statement,
                        "success_criteria": goal.success_criteria,
                    },
                    "attempt": {
                        "id": str(attempt.id),
                        "number": attempt.attempt_number,
                        "cycle_id": str(cycle.id),
                        "cycle_status": str(cycle.status),
                    },
                    "failure": failure,
                    "stage": stage,
                    "error_class": error_class,
                    "selected_paper_id": selected_paper_id,
                    "allowed_patch_fields": allowed_patch_fields,
                    "status_ledger": ledger,
                },
                indent=2,
                sort_keys=True,
                default=str,
            ),
        },
    ]
    router = ModelRouter()
    try:
        return await router.complete_structured(
            ModelRole.evaluation,
            messages,
            GoalRepairPlan,
            temperature=0.2,
            max_tokens=1600,
        )
    finally:
        await router.close()


def _ledger_summaries(goal_id: UUID) -> list[str]:
    return [
        str(entry.get("summary") or "")
        for entry in read_goal_status_ledger(goal_id).get("entries") or []
        if entry.get("summary")
    ][-8:]


def _fallback_stage_patch(stage: str, error_class: str) -> dict[str, Any]:
    if stage == "analysis":
        if error_class in {"timeout", "service_unavailable"}:
            return {
                "max_chunks": 80,
                "graph_extraction_concurrency": 1,
                "evidence_extraction_concurrency": 1,
            }
        return {"max_chunks": 120}
    if stage == "hypothesis":
        return {"max_hypotheses": 6, "max_critique_rounds": 1}
    return {}


def _apply_stage_retry(
    session,
    *,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    attempt: GoalAttempt,
    stage: str,
    failure: dict[str, Any],
    plan: GoalRepairPlan,
) -> dict[str, Any]:
    if stage == "analysis":
        paper_id_raw = failure.get("paper_card_id") or _latest_cycle_paper_id(session, cycle.id)
        if not paper_id_raw:
            return {"started": False, "summary": "cannot retry analysis without a paper"}
        paper = session.get(PaperCard, UUID(str(paper_id_raw)))
        if paper is None:
            return {"started": False, "summary": f"paper {paper_id_raw} not found"}
        analysis = _start_analysis_for_goal(
            session,
            goal,
            cycle,
            paper,
            config_patch=_allowed_stage_config_patch("analysis", plan.config_patch),
        )
        return {
            "started": True,
            "summary": f"started repaired analysis session {analysis.id}",
            "analysis_session_id": str(analysis.id),
        }

    if stage == "hypothesis":
        hs = _start_hypothesis_for_goal(
            session,
            goal,
            cycle,
            config_patch=_allowed_stage_config_patch("hypothesis", plan.config_patch),
        )
        return {
            "started": True,
            "summary": f"started repaired hypothesis session {hs.id}",
            "hypothesis_session_id": str(hs.id),
        }

    if stage == "protocol":
        result = _advance_from_portfolio(session, goal, cycle, attempt)
        return {"started": result["next_action"] != "blocked", "summary": result["summary"]}

    if stage == "discovery":
        discovery = _start_repaired_discovery_for_goal(
            session,
            goal,
            cycle,
            config_patch=_allowed_stage_config_patch("discovery", plan.config_patch),
        )
        return {
            "started": True,
            "summary": f"started repaired discovery session {discovery.id}",
            "discovery_session_id": str(discovery.id),
        }

    return {"started": False, "summary": f"no retry implementation for stage {stage}"}


def _allowed_stage_config_patch(stage: str, patch: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "analysis": {
            "max_chunks",
            "graph_extraction_concurrency",
            "evidence_extraction_concurrency",
            "html_quality_threshold",
        },
        "hypothesis": {"max_hypotheses", "max_critique_rounds"},
        "protocol": {"hardware_profile", "base_image"},
        "discovery": {"budget", "source_scope", "query_text", "notes"},
    }
    stage_allowed = allowed.get(stage, set())
    return {key: value for key, value in (patch or {}).items() if key in stage_allowed}


def _start_repaired_discovery_for_goal(
    session,
    goal: ResearchGoal,
    cycle: ResearchCycle,
    *,
    config_patch: dict[str, Any],
) -> DiscoverySession:
    profile = session.execute(
        select(ProblemProfile).where(ProblemProfile.cycle_id == cycle.id)
    ).scalar_one_or_none()
    if profile is None:
        raise GoalServiceError(f"problem profile for cycle {cycle.id} not found")
    if config_patch.get("query_text"):
        profile.query_text = str(config_patch["query_text"])
    if config_patch.get("notes"):
        profile.notes = str(config_patch["notes"])
    if config_patch.get("source_scope"):
        profile.source_scope = dict(config_patch["source_scope"])
    if config_patch.get("budget"):
        profile.budget = dict(config_patch["budget"])
    profile.updated_at = utcnow()

    discovery = DiscoverySession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=goal.charter_id,
        profile_id=profile.id,
        status="created",
        view=profile.view_preference,
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(discovery)
    session.flush()
    create_job(
        session,
        cycle_id=cycle.id,
        job_type="discovery_intake",
        payload={"session_id": str(discovery.id)},
        priority=10,
    )
    return discovery


def _block_or_next_attempt(
    session,
    *,
    goal: ResearchGoal,
    attempt: GoalAttempt,
    stage: str,
    summary: str,
    repair_plan: dict[str, Any] | None = None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    attempt.status = "blocked"
    attempt.completed_at = utcnow()
    attempt.updated_at = attempt.completed_at
    evaluation = dict(attempt.evaluation or {})
    evaluation["blocked_reason"] = summary
    evaluation["repair_plan"] = repair_plan
    evaluation["status_ledger"] = {
        "json_path": goal_status_paths(goal.id)["json"],
        "markdown_path": goal_status_paths(goal.id)["markdown"],
        "latest": latest_goal_status_summary(goal.id),
    }
    attempt.evaluation = evaluation
    append_goal_ledger_entry(
        session,
        goal,
        attempt,
        kind="blocked",
        stage=stage,
        summary=summary,
        outcome="blocked",
        fingerprint=fingerprint,
        repair_plan=repair_plan,
        cycle_id=attempt.cycle_id,
    )
    emit_event_sync(
        session,
        event_type=GoalEvents.advance_blocked.value,
        charter_id=goal.charter_id,
        cycle_id=attempt.cycle_id,
        payload={"goal_id": str(goal.id), "attempt_id": str(attempt.id), "stage": stage},
        actor_type=ActorType.worker,
    )
    if _budget_exhausted(session, goal):
        goal.status = GoalStatus.exhausted.value
        goal.completed_at = utcnow()
        goal.updated_at = goal.completed_at
        paths = write_goal_report(session, goal)
        goal.report_path = paths["markdown"]
        goal.report_json_path = paths["json"]
        return {"next_action": "exhausted", "summary": summary}

    start_goal_attempt_sync(session, goal, prior_attempt_summary=summary)
    paths = write_goal_report(session, goal)
    goal.report_path = paths["markdown"]
    goal.report_json_path = paths["json"]
    return {"next_action": "next_attempt_started", "summary": summary}


def evaluate_goal_attempt_sync(
    session,
    *,
    goal_id: UUID,
    cycle_id: UUID,
    cycle_report_paths: list[str] | None = None,
    force_recompute: bool = False,
) -> tuple[ResearchGoal, GoalAttempt, dict[str, Any]]:
    """Evaluate a closed cycle attempt and schedule the next goal action."""
    goal = session.get(ResearchGoal, goal_id)
    if goal is None:
        raise GoalServiceError(f"goal {goal_id} not found")

    attempt = session.execute(
        select(GoalAttempt).where(
            GoalAttempt.goal_id == goal_id,
            GoalAttempt.cycle_id == cycle_id,
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise GoalServiceError(f"goal attempt for cycle {cycle_id} not found")
    if attempt.completed_at is not None and not force_recompute:
        return goal, attempt, {
            "evaluation": attempt.evaluation or {},
            "next_action": "already_evaluated",
        }

    paths = _read_cycle_report_paths(cycle_report_paths)
    evaluation = evaluate_criteria(session, goal, cycle_id=cycle_id, report_paths=paths)
    evaluation["status_ledger"] = {
        "json_path": goal_status_paths(goal.id)["json"],
        "markdown_path": goal_status_paths(goal.id)["markdown"],
        "latest": latest_goal_status_summary(goal.id),
    }
    attempt.evaluation = evaluation
    attempt.status = "satisfied" if evaluation["passed"] else "failed"
    attempt.report_path = paths.get("markdown")
    attempt.report_json_path = paths.get("json")
    attempt.completed_at = utcnow()
    attempt.updated_at = attempt.completed_at

    goal.summary = evaluation["summary"]
    goal.updated_at = utcnow()

    if evaluation["passed"]:
        goal.status = GoalStatus.satisfied.value
        goal.completed_at = utcnow()
        next_action = "satisfied"
        event_type = GoalEvents.satisfied.value
    elif _budget_exhausted(session, goal):
        goal.status = GoalStatus.exhausted.value
        goal.completed_at = utcnow()
        next_action = "exhausted"
        event_type = GoalEvents.exhausted.value
    elif goal.status == GoalStatus.stopped.value:
        next_action = "stopped"
        event_type = GoalEvents.stopped.value
    else:
        start_goal_attempt_sync(
            session,
            goal,
            prior_attempt_summary=evaluation["summary"],
        )
        next_action = "next_attempt_started"
        event_type = GoalEvents.attempt_evaluated.value

    report_paths = write_goal_report(session, goal)
    goal.report_path = report_paths["markdown"]
    goal.report_json_path = report_paths["json"]

    emit_event_sync(
        session,
        event_type=event_type,
        charter_id=goal.charter_id,
        cycle_id=cycle_id,
        payload={
            "goal_id": str(goal.id),
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "passed": evaluation["passed"],
            "next_action": next_action,
        },
        actor_type=ActorType.worker,
    )
    return goal, attempt, {"evaluation": evaluation, "next_action": next_action}


def evaluate_criteria(
    session,
    goal: ResearchGoal,
    *,
    cycle_id: UUID,
    report_paths: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Evaluate deterministic goal criteria."""
    criteria = list(goal.success_criteria or [])
    cycle_ids = _goal_cycle_ids(session, goal.id)
    attempt_runs = _runs_for_cycles(session, [cycle_id])
    cumulative_runs = _runs_for_cycles(session, cycle_ids)
    report_paths = report_paths or {}
    results = []
    for raw in criteria:
        scope = raw.get("scope", "cumulative")
        runs = cumulative_runs if scope == "cumulative" else attempt_runs
        result = _evaluate_one(session, raw, runs, cycle_ids, cycle_id, report_paths)
        results.append(result)

    required = [r for r in results if r["required"]]
    passed = all(r["passed"] for r in required)
    passed_count = sum(1 for r in results if r["passed"])
    summary = f"{passed_count}/{len(results)} goal criteria passed"
    if not passed:
        failed = ", ".join(r["name"] for r in required if not r["passed"])
        summary = f"{summary}; failed required criteria: {failed or 'none'}"
    return {"passed": passed, "summary": summary, "criteria": results}


def _evaluate_one(
    session,
    criterion: dict[str, Any],
    runs: list[RunRecord],
    cycle_ids: list[UUID],
    cycle_id: UUID,
    report_paths: dict[str, str | None],
) -> dict[str, Any]:
    check_type = criterion.get("check_type")
    params = criterion.get("params") or {}
    passed = False
    detail = ""
    if check_type == "completed_run_exists":
        passed = any(run.status == "completed" for run in runs)
        detail = "found completed run" if passed else "no completed run found"
    elif check_type == "metric_present":
        metric = str(
            params.get("metric")
            or params.get("metric_name")
            or params.get("name")
            or ""
        )
        passed = any(metric in (run.metrics_output or {}) for run in runs)
        detail = f"metric {metric!r} {'found' if passed else 'missing'}"
    elif check_type == "metric_threshold":
        metric = str(
            params.get("metric")
            or params.get("metric_name")
            or params.get("name")
            or ""
        )
        op = str(params.get("operator") or params.get("op") or ">=")
        if params.get("value") is None:
            detail = "metric_threshold missing params.value"
        else:
            threshold = float(params.get("value"))
            values = [
                float((run.metrics_output or {})[metric])
                for run in runs
                if metric in (run.metrics_output or {})
                and isinstance((run.metrics_output or {})[metric], int | float)
            ]
            passed = any(_compare_metric(v, op, threshold) for v in values)
            detail = f"{metric} values={values} operator={op} threshold={threshold}"
    elif check_type == "artifact_exists":
        name = expected_artifact_name({
            "name": params.get("name") or params.get("artifact_name"),
            "path": params.get("path"),
        })
        path_contains = str(params.get("path_contains") or "")
        passed = any(
            _artifact_matches(item, name=name, path_contains=path_contains)
            for run in runs
            for item in (run.artifact_manifest or [])
        )
        detail = f"artifact name={name!r} path_contains={path_contains!r}"
    elif check_type == "verification_passed":
        accepted = params.get("accepted_verdicts")
        if isinstance(accepted, list) and accepted:
            verdicts = [str(verdict) for verdict in accepted if str(verdict)]
        else:
            verdicts = [str(params.get("verdict") or "passed")]
        passed = (
            session.execute(
                select(func.count())
                .select_from(VerificationReport)
                .where(VerificationReport.cycle_id.in_(cycle_ids or [cycle_id]))
                .where(VerificationReport.verdict.in_(verdicts))
            ).scalar_one()
            > 0
        )
        detail = f"verification verdict {', '.join(verdicts)!r}"
    elif check_type == "report_generated":
        passed = bool(report_paths.get("markdown") or report_paths.get("json"))
        detail = "cycle report path present" if passed else "cycle report path missing"
    else:
        detail = f"unsupported check_type {check_type!r}"

    return {
        "name": criterion.get("name") or check_type or "unnamed",
        "description": criterion.get("description") or "",
        "required": bool(criterion.get("required", True)),
        "check_type": check_type,
        "scope": criterion.get("scope", "cumulative"),
        "passed": passed,
        "detail": detail,
    }


def _compare_metric(value: float, op: str, threshold: float) -> bool:
    if op in (">=", "gte", "greater_equal"):
        return value >= threshold
    if op in (">", "gt", "greater"):
        return value > threshold
    if op in ("<=", "lte", "less_equal"):
        return value <= threshold
    if op in ("<", "lt", "less"):
        return value < threshold
    if op in ("==", "eq", "equal"):
        return value == threshold
    return False


def _artifact_matches(item: dict[str, Any], *, name: str, path_contains: str) -> bool:
    if name and item.get("name") != name:
        return False
    if path_contains and path_contains not in str(item.get("path", "")):
        return False
    return bool(name or path_contains)


def _goal_cycle_ids(session, goal_id: UUID) -> list[UUID]:
    return list(
        session.execute(
            select(GoalAttempt.cycle_id)
            .where(GoalAttempt.goal_id == goal_id)
            .order_by(GoalAttempt.attempt_number)
        ).scalars()
    )


def _runs_for_cycles(session, cycle_ids: list[UUID]) -> list[RunRecord]:
    if not cycle_ids:
        return []
    return list(
        session.execute(select(RunRecord).where(RunRecord.cycle_id.in_(cycle_ids)))
        .scalars()
        .all()
    )


def _read_cycle_report_paths(paths: list[str] | None) -> dict[str, str | None]:
    out = {"markdown": None, "json": None}
    for path in paths or []:
        if path.endswith(".md"):
            out["markdown"] = path
        elif path.endswith(".json"):
            out["json"] = path
    return out


def _budget_exhausted(session, goal: ResearchGoal) -> bool:
    policy = GoalPolicy.model_validate(goal.policy or {})
    attempts = session.execute(
        select(func.count()).select_from(GoalAttempt).where(GoalAttempt.goal_id == goal.id)
    ).scalar_one()
    if attempts >= policy.max_attempt_cycles:
        return True
    if policy.max_total_runs is not None:
        cycle_ids = _goal_cycle_ids(session, goal.id)
        total_runs = session.execute(
            select(func.count()).select_from(RunRecord).where(RunRecord.cycle_id.in_(cycle_ids))
        ).scalar_one()
        if total_runs >= policy.max_total_runs:
            return True
    if policy.max_wall_clock_hours is not None:
        elapsed = (utcnow() - _as_utc(goal.created_at)).total_seconds()
        if elapsed / 3600.0 >= policy.max_wall_clock_hours:
            return True
    return False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def write_goal_report(session, goal: ResearchGoal) -> dict[str, str]:
    """Write the goal-level report bundle."""
    settings = get_settings()
    root = Path(settings.data_root) / "reports" / "goals" / str(goal.id)
    root.mkdir(parents=True, exist_ok=True)
    result_summary = build_goal_result_summary(session, goal)
    payload = result_summary.model_dump(mode="json")
    payload["success_criteria"] = goal.success_criteria
    md = render_goal_result_markdown(result_summary)
    md_path = root / "report.md"
    json_path = root / "report.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    emit_event_sync(
        session,
        event_type=GoalEvents.report_generated.value,
        charter_id=goal.charter_id,
        cycle_id=None,
        payload={"goal_id": str(goal.id), "report_path": str(md_path)},
        actor_type=ActorType.worker,
    )
    return {"markdown": str(md_path), "json": str(json_path)}


def _render_goal_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Goal Report: {payload['title']}",
        "",
        f"- **Status:** {payload['status']}",
        f"- **Goal ID:** `{payload['goal_id']}`",
        f"- **Charter ID:** `{payload['charter_id']}`",
        "",
        "## Summary",
        "",
        payload.get("summary") or "No evaluation has completed yet.",
        "",
        "## Status Ledger",
        "",
        f"- **Markdown:** `{payload['status_ledger']['markdown_path']}`",
        f"- **JSON:** `{payload['status_ledger']['json_path']}`",
        "",
        "## Attempts",
        "",
    ]
    attempts = payload.get("attempts") or []
    if not attempts:
        lines.append("No attempts have been recorded yet.")
    else:
        lines.extend(["| # | Status | Cycle | Criteria |", "|---|---|---|---|"])
        for attempt in attempts:
            evaluation = attempt.get("evaluation") or {}
            criteria = evaluation.get("criteria") or []
            passed = sum(1 for c in criteria if c.get("passed"))
            lines.append(
                f"| {attempt['attempt_number']} | {attempt['status']} | "
                f"`{attempt['cycle_id']}` | {passed}/{len(criteria)} |"
            )
    lines.extend(["", "## Criteria", ""])
    for criterion in payload.get("success_criteria") or []:
        lines.append(
            f"- **{criterion.get('name', criterion.get('check_type', 'criterion'))}:** "
            f"{criterion.get('description', '')}"
        )
    return "\n".join(lines) + "\n"


def read_goal_report_file(goal: ResearchGoal) -> tuple[str | None, dict[str, Any] | None]:
    markdown = None
    json_payload = None
    if goal.report_path and Path(goal.report_path).exists():
        markdown = Path(goal.report_path).read_text(encoding="utf-8")
    if goal.report_json_path and Path(goal.report_json_path).exists():
        json_payload = json.loads(Path(goal.report_json_path).read_text(encoding="utf-8"))
    return markdown, json_payload


def stop_goal_sync(session, goal_id: UUID) -> ResearchGoal:
    goal = session.get(ResearchGoal, goal_id)
    if goal is None:
        raise GoalServiceError(f"goal {goal_id} not found")
    goal.status = GoalStatus.stopped.value
    goal.completed_at = utcnow()
    goal.updated_at = goal.completed_at
    cycle_ids = _goal_cycle_ids(session, goal.id)
    if cycle_ids:
        session.execute(
            update(Job)
            .where(Job.cycle_id.in_(cycle_ids))
            .where(
                Job.status.in_(
                    [
                        JobStatus.pending.value,
                        JobStatus.claimed.value,
                        JobStatus.running.value,
                        JobStatus.paused.value,
                    ]
                )
            )
            .values(status=JobStatus.cancelled)
        )
    emit_event_sync(
        session,
        event_type=GoalEvents.stopped.value,
        charter_id=goal.charter_id,
        cycle_id=None,
        payload={"goal_id": str(goal.id)},
        actor_type=ActorType.user,
    )
    return goal
