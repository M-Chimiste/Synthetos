"""verification_postmortem operator -- generates a structured failure
postmortem using the evaluation model role.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.event_types import VerificationEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.services.job_service import create_job
from libs.discovery.skill_support import join_skill_prompts, load_skill_prompt
from libs.execution.operators._common import (
    ExecutionStateError,
    load_run_record,
    run_record_id_from_payload,
)
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call, record_skill_usage
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import (
    FailurePostmortem,
    VerificationReport,
)

log = get_logger("verification.postmortem")


class _PostmortemOutput(BaseModel):
    """Structured output from the postmortem LLM call."""

    root_cause: str
    contributing_factors: list[dict[str, Any]] = Field(default_factory=list)
    next_step_recommendation: str = ""
    lessons: list[dict[str, Any]] = Field(default_factory=list)


async def _generate_postmortem(
    failure_class: str,
    error: str,
    error_trace: str,
    metrics_output: dict[str, Any] | None,
    baseline_comparison: dict[str, Any] | None,
    skill_prompt: str | None,
) -> tuple[_PostmortemOutput, dict[str, Any]]:
    """Call the LLM to generate a failure postmortem."""
    router = ModelRouter()
    try:
        system_msg = (
            "You are an ML experiment failure analyst. Given a failed experiment run, "
            "determine the root cause, contributing factors, and recommend next steps. "
            "Be specific and actionable."
        )
        system_msg = join_skill_prompts(system_msg, skill_prompt) or system_msg
        user_msg = (
            f"Failure class: {failure_class}\n"
            f"Error: {error}\n\n"
            f"Error trace (last 50 lines):\n{error_trace}\n\n"
            f"Metrics output: {metrics_output}\n"
            f"Baseline comparison: {baseline_comparison}\n\n"
            "Analyze this failure and provide:\n"
            "1. Root cause\n"
            "2. Contributing factors\n"
            "3. Next step recommendation\n"
            "4. Lessons learned"
        )
        result = await router.complete_structured(
            role=ModelRole.evaluation,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_PostmortemOutput,
            temperature=0.3,
        )
        return result, router.get_role_config(ModelRole.evaluation)
    finally:
        await router.close()


def verification_postmortem_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as db:
        run = load_run_record(db, run_id)

        # Load verification report if it exists
        from sqlalchemy import select

        vr = db.execute(
            select(VerificationReport).where(VerificationReport.run_record_id == run.id)
        ).scalar_one_or_none()

        # Read error trace from stderr file
        error_trace = ""
        if run.stderr_path:
            stderr_path = Path(run.stderr_path)
            if stderr_path.exists():
                lines = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
                error_trace = "\n".join(lines[-50:])
        elif run.stdout_path:
            stdout_path = Path(run.stdout_path)
            if stdout_path.exists():
                lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
                error_trace = "\n".join(lines[-50:])

        skill_result = load_skill_prompt(
            db,
            skill_id="verification.run_evaluation",
            operator_type=op_input.job_type,
        )
        if skill_result.prompt:
            record_skill_usage(
                db,
                skill_id="verification.run_evaluation",
                cycle_id=run.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
            )

        # Generate postmortem via LLM
        try:
            pm_output, role_cfg = asyncio.run(
                _generate_postmortem(
                    failure_class=run.failure_class or "unknown",
                    error=run.error or "unknown error",
                    error_trace=error_trace,
                    metrics_output=run.metrics_output,
                    baseline_comparison=vr.baseline_comparison if vr else None,
                    skill_prompt=skill_result.prompt,
                )
            )
            record_model_call(
                db,
                cycle_id=run.cycle_id,
                job_id=op_input.job_id,
                role=ModelRole.evaluation.value,
                provider=str(role_cfg.get("provider", "unknown")),
                model_id=str(role_cfg.get("model", "unknown")),
            )
        except Exception as exc:
            # If LLM fails, create a basic postmortem
            pm_output = _PostmortemOutput(
                root_cause=f"Automated analysis unavailable: {exc}",
                next_step_recommendation="Review error trace manually",
            )

        postmortem = FailurePostmortem(
            id=uuid7(),
            run_record_id=run.id,
            verification_report_id=vr.id if vr else None,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            failure_class=run.failure_class or "unknown",
            root_cause=pm_output.root_cause,
            contributing_factors=pm_output.contributing_factors or None,
            error_trace=error_trace or None,
            next_step_recommendation=pm_output.next_step_recommendation or None,
            lessons=pm_output.lessons or None,
            created_at=utcnow(),
        )
        db.add(postmortem)

        emit_event_sync(
            db,
            event_type=VerificationEvents.postmortem_generated.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "postmortem_id": str(postmortem.id),
                "failure_class": postmortem.failure_class,
            },
        )

        # Enqueue recommend operator (it owns the transition to reporting)
        create_job(
            db,
            cycle_id=run.cycle_id,
            job_type="recommend",
            payload={"run_record_id": str(run.id), "failed": True},
            priority=10,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Postmortem for run {run_id} ({postmortem.failure_class}); enqueued recommend",
    )
