"""execution_run operator -- launches the Docker container, streams logs,
captures telemetry, and enqueues the next step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from uuid_utils import uuid7

from libs.adapters.container.docker_runner import DockerRunner, RunSpec
from libs.adapters.git.worktree import cleanup_worktree
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import ExecutionEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.execution.operators._common import (
    ExecutionStateError,
    enqueue_next,
    load_run_record,
    run_record_id_from_payload,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import RunTelemetry

log = get_logger("execution.run")

# Failure classification heuristics
_OOM_SIGNALS = ["oom", "out of memory", "killed", "signal 9"]
_TIMEOUT_SIGNALS = ["timeout"]
_DEPENDENCY_SIGNALS = ["modulenotfounderror", "importerror", "no such file"]


def _classify_failure(exit_code: int, stderr_tail: str) -> str:
    """Classify a run failure based on exit code and stderr content."""
    lower = stderr_tail.lower()
    if exit_code == 137 or any(s in lower for s in _OOM_SIGNALS):
        return "oom"
    if any(s in lower for s in _TIMEOUT_SIGNALS):
        return "timeout"
    if any(s in lower for s in _DEPENDENCY_SIGNALS):
        return "dependency"
    if exit_code != 0:
        return "runtime"
    return "unknown"


def execution_run_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    settings = get_settings()

    with factory() as db:
        run = load_run_record(db, run_id)
        resume_requested = bool(op_input.payload.get("resume"))
        run.status = "running"
        db.flush()

        workspace_path = Path(run.workspace_path) if run.workspace_path else None
        if workspace_path is None or not workspace_path.exists():
            run.status = "failed"
            run.failure_class = "dependency"
            run.error = "workspace path does not exist"
            run.completed_at = utcnow()
            db.commit()
            return OperatorResult(success=False, error=run.error)

        artifact_path = settings.data_root / "artifacts" / str(run.id)
        artifact_path.mkdir(parents=True, exist_ok=True)

        # Set up stdout/stderr paths
        log_dir = settings.data_root / "logs" / str(run.id)
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"
        run.stdout_path = str(stdout_path)
        run.stderr_path = str(stderr_path)

        limits = run.resource_limits or {}

        spec = RunSpec(
            workspace_path=workspace_path,
            image=run.image_ref or "python:3.12-slim",
            command=["sh", "-c", run.command or "python run_experiment.py"],
            env=dict(run.env_vars or {}),
            gpu_enabled=bool(limits.get("gpu", False)),
            gpu_count=int(limits.get("gpu_count", 1)),
            memory_limit=str(limits.get("memory", "16g")),
            timeout_seconds=int(limits.get("timeout", 3600)),
            artifact_output_path=artifact_path,
        )

        # Telemetry callback — writes rows to DB immediately so other sessions can see them.
        log_lines: list[str] = []
        last_progress_at = 0.0

        def telemetry_callback(event_type: str, message: str, payload: dict[str, Any]) -> None:
            log_lines.append(message)
            with factory() as telemetry_db:
                row = RunTelemetry(
                    id=uuid7(),
                    run_record_id=run.id,
                    timestamp=utcnow(),
                    event_type=event_type,
                    payload={"message": message, **payload},
                )
                telemetry_db.add(row)
                telemetry_db.commit()

        def control_callback() -> Literal["pause", "cancel"] | None:
            nonlocal last_progress_at
            now = utcnow().timestamp()
            with factory() as control_db:
                fresh_run = load_run_record(control_db, run.id)
                if fresh_run.status == "cancelled":
                    return "cancel"
                if fresh_run.status == "paused":
                    return "pause"

                if now - last_progress_at >= 30:
                    last_progress_at = now
                    emit_event_sync(
                        control_db,
                        event_type=ExecutionEvents.run_progress.value,
                        charter_id=fresh_run.charter_id,
                        cycle_id=fresh_run.cycle_id,
                        payload={
                            "run_record_id": str(fresh_run.id),
                            "wall_time_s": max(
                                0,
                                int(
                                    now
                                    - (
                                        fresh_run.started_at or utcnow()
                                    ).timestamp()
                                ),
                            ),
                            "status": fresh_run.status,
                        },
                    )
                    control_db.commit()
            return None

        emit_event_sync(
            db,
            event_type=ExecutionEvents.container_started.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "image": spec.image,
                "resume": resume_requested,
            },
        )
        db.commit()

        # Execute container
        runner = DockerRunner()
        try:
            outcome = runner.run(
                spec,
                telemetry_callback=telemetry_callback,
                control_callback=control_callback,
                resume_container_id=run.container_id if resume_requested else None,
            )
        except Exception as exc:
            run.status = "failed"
            run.failure_class = "runtime"
            run.error = f"container execution failed: {exc}"
            run.completed_at = utcnow()
            db.commit()
            return OperatorResult(success=False, error=run.error)

        # Write log files
        stdout_path.write_text("\n".join(log_lines), encoding="utf-8")

        # Update run record
        run.container_id = outcome.container_id
        run.exit_code = outcome.exit_code if outcome.exit_code >= 0 else None
        run.resource_usage = outcome.resource_usage

        if outcome.terminal_state == "paused":
            run.status = "paused"
            run.updated_at = utcnow()
            db.commit()
            return OperatorResult(
                success=True,
                summary=outcome.status_message or "Run paused",
            )

        if outcome.terminal_state == "cancelled":
            run.status = "cancelled"
            run.completed_at = utcnow()
            run.updated_at = utcnow()
            if run.workspace_path:
                cleanup_worktree(settings.repo_root, Path(run.workspace_path))
            db.commit()
            return OperatorResult(
                success=True,
                summary=outcome.status_message or "Run cancelled",
            )

        if outcome.exit_code != 0:
            stderr_tail = "\n".join(log_lines[-50:]) if log_lines else ""
            run.failure_class = _classify_failure(outcome.exit_code, stderr_tail)
            run.status = "failed"
            run.error = f"container exited with code {outcome.exit_code}"
            run.completed_at = utcnow()

            emit_event_sync(
                db,
                event_type=ExecutionEvents.run_failed.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "exit_code": outcome.exit_code,
                    "failure_class": run.failure_class,
                },
            )

            # Enqueue verification even for failures (to generate postmortem)
            enqueue_next(
                db,
                cycle_id=run.cycle_id,
                next_job_type="verification_check",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,  # operator succeeded; the *run* failed
                summary=f"Run failed with exit code {outcome.exit_code} ({run.failure_class})",
                state_patch={"cycle_status": CycleStatus.verifying.value},
            )

        # Success path — enqueue capture
        run.status = "capturing"

        emit_event_sync(
            db,
            event_type=ExecutionEvents.run_completed.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "exit_code": 0,
                "wall_time_s": outcome.wall_time_s,
            },
        )

        enqueue_next(
            db,
            cycle_id=run.cycle_id,
            next_job_type="execution_capture",
            run_record_id=run.id,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"Container exited 0 in {outcome.wall_time_s}s; enqueued execution_capture",
    )
