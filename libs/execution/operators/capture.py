"""execution_capture operator -- collects artifact manifest, parses metrics,
and transitions to verification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import ExecutionEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.execution.metrics import parse_metrics
from libs.execution.operators._common import (
    ExecutionStateError,
    enqueue_next,
    load_run_record,
    run_record_id_from_payload,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import ExperimentSpec

log = get_logger("execution.capture")


def _collect_artifacts(artifact_dir: Path) -> list[dict]:
    """Walk the artifact directory and build a manifest."""
    manifest = []
    if not artifact_dir.exists():
        return manifest

    for file_path in sorted(artifact_dir.rglob("*")):
        if file_path.is_file():
            size = file_path.stat().st_size
            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            manifest.append({
                "name": file_path.name,
                "path": str(file_path.relative_to(artifact_dir)),
                "size_bytes": size,
                "hash": content_hash,
            })
    return manifest


def execution_capture_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        run_id = run_record_id_from_payload(op_input)
    except ExecutionStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    settings = get_settings()

    with factory() as db:
        run = load_run_record(db, run_id)
        spec = db.get(ExperimentSpec, run.experiment_spec_id)
        if spec is None:
            return OperatorResult(success=False, error="experiment spec not found")

        artifact_dir = settings.data_root / "artifacts" / str(run.id)

        # 1. Collect artifact manifest
        manifest = _collect_artifacts(artifact_dir)
        run.artifact_manifest = manifest

        # 2. Parse metrics
        expected_metrics = spec.metrics or []
        parsed = parse_metrics(artifact_dir, expected_metrics)

        if parsed.ok:
            run.metrics_output = parsed.values
        else:
            # Metric parse errors → run fails before verification
            run.metrics_output = parsed.values  # store what we could parse
            run.status = "failed"
            run.failure_class = "metric_parse"
            run.error = "; ".join(parsed.errors)
            run.completed_at = utcnow()

            emit_event_sync(
                db,
                event_type=ExecutionEvents.run_failed.value,
                charter_id=run.charter_id,
                cycle_id=run.cycle_id,
                payload={
                    "run_record_id": str(run.id),
                    "failure_class": "metric_parse",
                    "errors": parsed.errors,
                },
            )

            # Still enqueue verification to generate postmortem
            enqueue_next(
                db,
                cycle_id=run.cycle_id,
                next_job_type="verification_check",
                run_record_id=run.id,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Metric parse failed: {'; '.join(parsed.errors)}",
                state_patch={"cycle_status": CycleStatus.verifying.value},
            )

        # Success path
        run.status = "completed"
        run.completed_at = utcnow()

        emit_event_sync(
            db,
            event_type=ExecutionEvents.artifacts_captured.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={
                "run_record_id": str(run.id),
                "artifact_count": len(manifest),
                "metric_count": len(parsed.values),
            },
        )

        enqueue_next(
            db,
            cycle_id=run.cycle_id,
            next_job_type="verification_check",
            run_record_id=run.id,
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=(
            f"Captured {len(manifest)} artifacts, {len(parsed.values)} metrics; "
            "enqueued verification_check"
        ),
        state_patch={"cycle_status": CycleStatus.verifying.value},
    )
