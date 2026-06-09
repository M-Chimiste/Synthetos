"""auto_remediate operator -- attempts to fix mechanical failures before
generating a postmortem. Creates a new RunRecord for retry when possible.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import RemediationEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.patterns.embedding import embed_text
from libs.patterns.injection import InjectionPolicy, inject_patterns
from libs.remediation.operators._common import (
    ExecutionStateError,
    count_lineage_attempts,
    enqueue_next_phase4,
    load_experiment_spec,
    load_lineage_actions,
    load_run_record,
    run_record_id_from_payload,
)
from libs.remediation.strategies import select_strategy
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import RunRecord
from libs.storage.models.remediation import RemediationAction
from libs.storage.models.research import ResearchCycle

log = get_logger("remediation.remediate")

DEFAULT_MAX_ATTEMPTS = 3


class _BroadDebugOutput(BaseModel):
    """Structured output from the broad debug LLM call."""

    patched_files: dict[str, str] = Field(
        default_factory=dict,
        description="Map of filepath -> new content for files to patch.",
    )
    explanation: str = ""


class _BuildRemediationOutput(BaseModel):
    """Structured output from focused image-build remediation."""

    dockerfile_content: str | None = Field(
        default=None,
        description="Full replacement Dockerfile content for dockerfile_fix.",
    )
    base_image: str | None = Field(
        default=None,
        description="Replacement base image tag for base_image_swap.",
    )
    explanation: str = ""


async def _broad_debug_llm(
    error_trace: str,
    code_plan: dict[str, Any] | None,
    prior_remediation: list[dict[str, Any]],
    pattern_hints: list[dict[str, Any]] | None = None,
) -> _BroadDebugOutput | None:
    """Call LLM for broad debug remediation. Returns None on failure."""
    from libs.adapters.llm.router import ModelRouter
    from libs.schemas.model_gateway import ModelRole

    router = ModelRouter()
    try:
        system_msg = (
            "You are an ML experiment debugger. Given a failed experiment's error trace "
            "and source code, suggest specific file patches to fix the issue. "
            "Only suggest changes that are likely to fix the root cause. "
            "If the failure involves DNS, name resolution, Hugging Face, datasets, "
            "tokenizer/model downloads, or any unavailable network resource, keep the "
            "scientific intent but make the next attempt fast and robust: use streaming "
            "datasets or tiny explicit splits, cap examples/batches, and add a "
            "deterministic synthetic/local fallback when the dataset cannot be reached. "
            "Avoid large runtime model/tokenizer downloads for quick E2E experiments; "
            "prefer tiny in-code torch models or clearly bounded cached paths when "
            "supplied. Preserve required artifact outputs, especially "
            "/artifacts/metrics.json and /artifacts/model_weights.pt for training jobs."
        )
        hint_text = ""
        if pattern_hints:
            hint_lines = [
                f"- [{h['pattern_type']}] {h['title']}: {h['summary']}"
                for h in pattern_hints
            ]
            hint_text = (
                "Canonical remediation patterns that previously matched this failure:\n"
                + "\n".join(hint_lines)
                + "\n\n"
            )
        user_msg = (
            f"Error trace (last 50 lines):\n{error_trace}\n\n"
            f"Code plan files:\n{_format_code_plan(code_plan)}\n\n"
            f"Prior remediation attempts:\n{prior_remediation}\n\n"
            f"{hint_text}"
            "Provide patched file contents to fix this error."
        )
        result = await router.complete_structured(
            role=ModelRole.evaluation,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_BroadDebugOutput,
            temperature=0.3,
        )
        return result
    except Exception as exc:
        log.warning("Broad debug LLM call failed", error=str(exc))
        return None
    finally:
        await router.close()


async def _build_remediation_llm(
    *,
    strategy: str,
    error_trace: str,
    build_log: str,
    current_dockerfile: str | None,
    current_base_image: str | None,
    prior_remediation: list[dict[str, Any]],
    pattern_hints: list[dict[str, Any]] | None = None,
) -> _BuildRemediationOutput | None:
    """Call LLM for focused Docker build remediation."""
    from libs.adapters.llm.router import ModelRouter
    from libs.schemas.model_gateway import ModelRole

    router = ModelRouter()
    try:
        if strategy == "dockerfile_fix":
            requested_output = (
                "Return dockerfile_content containing the complete replacement "
                "Dockerfile. Leave base_image null."
            )
        else:
            requested_output = (
                "Return base_image containing a replacement image tag. Leave "
                "dockerfile_content null unless a full Dockerfile is also required."
            )

        hint_text = ""
        if pattern_hints:
            hint_lines = [
                f"- [{h['pattern_type']}] {h['title']}: {h['summary']}"
                for h in pattern_hints
            ]
            hint_text = (
                "Canonical remediation patterns that previously matched this failure:\n"
                + "\n".join(hint_lines)
                + "\n\n"
            )

        system_msg = (
            "You are debugging a Docker image build for an ML experiment. "
            "Suggest the smallest focused build fix that is likely to make "
            "the next build succeed."
        )
        user_msg = (
            f"Strategy: {strategy}\n\n"
            f"Build failure summary:\n{error_trace or '(none)'}\n\n"
            f"Full build log:\n{build_log or '(not available)'}\n\n"
            f"Current base image:\n{current_base_image or '(default python:3.12-slim)'}\n\n"
            f"Current Dockerfile:\n{current_dockerfile or '(no custom Dockerfile)'}\n\n"
            f"Prior remediation attempts:\n{prior_remediation}\n\n"
            f"{hint_text}"
            f"{requested_output}"
        )
        return await router.complete_structured(
            role=ModelRole.evaluation,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_BuildRemediationOutput,
            temperature=0.3,
        )
    except Exception as exc:
        log.warning("Build remediation LLM call failed", strategy=strategy, error=str(exc))
        return None
    finally:
        await router.close()


def _format_code_plan(code_plan: dict[str, Any] | None) -> str:
    """Format code plan files for the LLM prompt."""
    if not code_plan:
        return "(no code plan)"
    metadata_parts = []
    if code_plan.get("entry_point"):
        metadata_parts.append(f"Entry point: {code_plan['entry_point']}")
    if code_plan.get("dependencies"):
        metadata_parts.append(f"Dependencies: {code_plan['dependencies']}")
    if code_plan.get("expected_metrics"):
        metadata_parts.append(f"Expected metrics: {code_plan['expected_metrics']}")
    if code_plan.get("expected_artifacts"):
        metadata_parts.append(f"Expected artifacts: {code_plan['expected_artifacts']}")
    files = code_plan.get("files", {})
    parts = []
    if metadata_parts:
        parts.append("\n".join(metadata_parts))
    for name, content in files.items():
        parts.append(f"--- {name} ---\n{content}")
    return "\n\n".join(parts) if parts else "(no files in code plan)"


def _read_build_log(run: RunRecord) -> str:
    """Read the full build log captured in the failed run's worktree."""
    if not run.workspace_path:
        return ""
    build_log_path = Path(run.workspace_path) / "build.log"
    if not build_log_path.exists():
        return ""
    return build_log_path.read_text(encoding="utf-8", errors="replace")


def _current_dockerfile(spec) -> str | None:
    build_recipe = spec.build_recipe if isinstance(spec.build_recipe, dict) else None
    if not build_recipe:
        return None
    dockerfile = build_recipe.get("dockerfile_content")
    return dockerfile if isinstance(dockerfile, str) else None


def auto_remediate_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = load_experiment_spec(db, run.experiment_spec_id)

        emit_event_sync(
            db,
            event_type=RemediationEvents.remediation_started.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "failure_class": run.failure_class or "unknown",
            },
        )

        # Count prior attempts in lineage
        attempt_count = count_lineage_attempts(db, run.id)
        attempt_number = attempt_count + 1

        if attempt_count >= DEFAULT_MAX_ATTEMPTS:
            # Exhausted — record and forward to postmortem
            action = RemediationAction(
                id=uuid7(),
                run_record_id=run.id,
                retry_run_id=None,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                experiment_spec_id=spec.id,
                failure_class=run.failure_class or "unknown",
                strategy="skip",
                strategy_tier="focused",
                action_detail=None,
                outcome="exhausted",
                attempt_number=attempt_number,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                reasoning=f"Max remediation attempts ({DEFAULT_MAX_ATTEMPTS}) reached.",
                created_at=utcnow(),
            )
            db.add(action)

            emit_event_sync(
                db,
                event_type=RemediationEvents.exhausted.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "attempt_number": attempt_number,
                    "max_attempts": DEFAULT_MAX_ATTEMPTS,
                },
            )

            enqueue_next_phase4(
                db,
                cycle_id=run.cycle_id,
                next_job_type="verification_postmortem",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Remediation exhausted ({attempt_count} attempts); enqueued postmortem",
            )

        # Load stderr for strategy selection
        stderr_tail = ""
        if run.stderr_path:
            stderr_path = Path(run.stderr_path)
            if stderr_path.exists():
                lines = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
                stderr_tail = "\n".join(lines[-50:])
        elif run.stdout_path:
            stdout_path = Path(run.stdout_path)
            if stdout_path.exists():
                lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
                stderr_tail = "\n".join(lines[-50:])
        failure_context = "\n".join(
            part for part in [run.error, stderr_tail] if part
        ).strip()

        # Load prior strategies in lineage
        prior_actions = load_lineage_actions(db, run.id)
        prior_strategies = [a.strategy for a in prior_actions]
        prior_failure_classes = [a.failure_class for a in prior_actions]
        prior_detail = [
            {"strategy": a.strategy, "failure_class": a.failure_class, "outcome": a.outcome}
            for a in prior_actions
        ]

        # Phase 6: retrieve remediation patterns matching this failure_class as
        # priors. We don't override strategy selection (deterministic path stays
        # in charge), but we record matched patterns on the action for audit and
        # feed them to the broad-debug LLM as additional context.
        cycle = db.get(ResearchCycle, run.cycle_id)
        pattern_policy = InjectionPolicy.from_cycle_config(
            cycle.config if cycle else None
        )
        remediation_pattern_matches = inject_patterns(
            db,
            charter_id=run.charter_id,
            current_cycle_id=run.cycle_id,
            types=["remediation", "failure"],
            policy=pattern_policy,
            problem_profile_embedding=embed_text(
                "\n".join(
                    [
                        run.failure_class or "unknown",
                        failure_context,
                        spec.title,
                        spec.description,
                    ]
                )
            ),
            operator_name="auto_remediate",
        )
        remediation_pattern_hints = [
            m.to_context()
            for m in remediation_pattern_matches
            if m.pattern.structured_body.get("failure_class")
            == (run.failure_class or "unknown")
        ]

        # Select strategy
        strat = select_strategy(
            failure_class=run.failure_class or "unknown",
            stderr_tail=stderr_tail,
            current_resource_limits=run.resource_limits,
            prior_strategies=prior_strategies,
            prior_failure_classes=prior_failure_classes,
            expected_artifacts=spec.expected_artifacts,
            artifact_manifest=run.artifact_manifest,
            code_plan=spec.code_plan,
        )

        if not strat.remediable:
            # Non-remediable — skip to postmortem
            action = RemediationAction(
                id=uuid7(),
                run_record_id=run.id,
                retry_run_id=None,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                experiment_spec_id=spec.id,
                failure_class=run.failure_class or "unknown",
                strategy=strat.strategy,
                strategy_tier=strat.strategy_tier,
                action_detail=None,
                outcome="skipped",
                attempt_number=attempt_number,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                reasoning=strat.reasoning,
                created_at=utcnow(),
            )
            db.add(action)

            emit_event_sync(
                db,
                event_type=RemediationEvents.skipped.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "failure_class": run.failure_class,
                    "reason": strat.reasoning,
                },
            )

            enqueue_next_phase4(
                db,
                cycle_id=run.cycle_id,
                next_job_type="verification_postmortem",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Not remediable ({strat.reasoning}); enqueued postmortem.",
            )

        # Focused build remediation requires a concrete build override before retrying.
        overrides = dict(strat.overrides)
        if strat.strategy in {"dockerfile_fix", "base_image_swap"}:
            try:
                build_result = asyncio.run(
                    _build_remediation_llm(
                        strategy=strat.strategy,
                        error_trace=run.error or stderr_tail,
                        build_log=_read_build_log(run),
                        current_dockerfile=_current_dockerfile(spec),
                        current_base_image=spec.base_image,
                        prior_remediation=prior_detail,
                        pattern_hints=remediation_pattern_hints,
                    )
                )
            except Exception:
                build_result = None

            if strat.strategy == "dockerfile_fix":
                dockerfile_content = (
                    build_result.dockerfile_content.strip()
                    if build_result and build_result.dockerfile_content
                    else ""
                )
                if dockerfile_content:
                    overrides["build_recipe"] = {
                        "dockerfile_content": dockerfile_content,
                    }
            else:
                base_image = (
                    build_result.base_image.strip()
                    if build_result and build_result.base_image
                    else ""
                )
                if base_image:
                    overrides["base_image"] = base_image

            if not overrides:
                action = RemediationAction(
                    id=uuid7(),
                    run_record_id=run.id,
                    retry_run_id=None,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    experiment_spec_id=spec.id,
                    failure_class=run.failure_class or "unknown",
                    strategy=strat.strategy,
                    strategy_tier=strat.strategy_tier,
                    action_detail=None,
                    outcome="skipped",
                    attempt_number=attempt_number,
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    reasoning=(
                        f"{strat.strategy} did not produce the required build override."
                    ),
                    created_at=utcnow(),
                )
                db.add(action)
                emit_event_sync(
                    db,
                    event_type=RemediationEvents.skipped.value,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    payload={
                        "run_record_id": str(run.id),
                        "failure_class": run.failure_class,
                        "reason": action.reasoning,
                    },
                )
                enqueue_next_phase4(
                    db,
                    cycle_id=run.cycle_id,
                    next_job_type="verification_postmortem",
                    run_record_id=run.id,
                )
                db.commit()
                return OperatorResult(
                    success=True,
                    summary=(
                        f"{strat.strategy} produced no build override; "
                        "enqueued postmortem."
                    ),
                )

        # Handle broad debug: call LLM for code fix
        if strat.strategy == "debug_broad":
            emit_event_sync(
                db,
                event_type=RemediationEvents.strategy_escalated.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "from_tier": "focused",
                    "to_tier": "broad",
                },
            )

            try:
                debug_code_plan = dict(spec.code_plan or {})
                debug_code_plan["expected_metrics"] = spec.metrics or []
                debug_code_plan["expected_artifacts"] = spec.expected_artifacts or []
                debug_result = asyncio.run(
                    _broad_debug_llm(
                        failure_context or stderr_tail,
                        debug_code_plan,
                        prior_detail,
                        pattern_hints=remediation_pattern_hints,
                    )
                )
            except Exception:
                debug_result = None

            if debug_result and debug_result.patched_files:
                overrides["code_plan"] = {"patched_files": debug_result.patched_files}
            else:
                # LLM couldn't produce a fix — treat as exhausted for this attempt
                action = RemediationAction(
                    id=uuid7(),
                    run_record_id=run.id,
                    retry_run_id=None,
                    charter_id=run.charter_id,
                    cycle_id=run.cycle_id,
                    experiment_spec_id=spec.id,
                    failure_class=run.failure_class or "unknown",
                    strategy="debug_broad",
                    strategy_tier="broad",
                    action_detail=None,
                    outcome="skipped",
                    attempt_number=attempt_number,
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    reasoning="Broad debug LLM could not produce a code fix.",
                    created_at=utcnow(),
                )
                db.add(action)
                enqueue_next_phase4(
                    db,
                    cycle_id=run.cycle_id,
                    next_job_type="verification_postmortem",
                    run_record_id=run.id,
                )
                db.commit()
                return OperatorResult(
                    success=True,
                    summary="Broad debug failed to produce fix; enqueued postmortem.",
                )

        # Create new RunRecord for retry
        new_resource_limits = dict(run.resource_limits or {})
        if "run_resource_limits" in overrides:
            new_resource_limits.update(overrides.pop("run_resource_limits"))

        retry_run = RunRecord(
            id=uuid7(),
            experiment_spec_id=run.experiment_spec_id,
            parent_run_id=run.id,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            run_number=run.run_number + 1,
            status="pending",
            resource_limits=new_resource_limits or None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(retry_run)
        db.flush()  # Get retry_run.id

        # Persist RemediationAction
        action = RemediationAction(
            id=uuid7(),
            run_record_id=run.id,
            retry_run_id=retry_run.id,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            experiment_spec_id=spec.id,
            failure_class=run.failure_class or "unknown",
            strategy=strat.strategy,
            strategy_tier=strat.strategy_tier,
            action_detail=overrides or None,
            outcome="retry_created",
            attempt_number=attempt_number,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            reasoning=strat.reasoning,
            created_at=utcnow(),
        )
        db.add(action)

        emit_event_sync(
            db,
            event_type=RemediationEvents.retry_created.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "retry_run_id": str(retry_run.id),
                "strategy": strat.strategy,
                "strategy_tier": strat.strategy_tier,
                "attempt_number": attempt_number,
            },
        )

        # Build remediation_overrides payload for execution_setup
        remediation_overrides = {}
        if "code_plan" in overrides:
            remediation_overrides["code_plan"] = overrides["code_plan"]
        if "build_recipe" in overrides:
            remediation_overrides["build_recipe"] = overrides["build_recipe"]
        if "base_image" in overrides:
            remediation_overrides["base_image"] = overrides["base_image"]

        enqueue_next_phase4(
            db,
            cycle_id=run.cycle_id,
            next_job_type="execution_setup",
            run_record_id=retry_run.id,
            extra_payload=(
                {"remediation_overrides": remediation_overrides}
                if remediation_overrides
                else None
            ),
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=(
            f"Remediation: {strat.strategy} ({strat.strategy_tier}); "
            f"created retry run {retry_run.id}"
        ),
        state_patch={"cycle_status": CycleStatus.running.value},
    )
