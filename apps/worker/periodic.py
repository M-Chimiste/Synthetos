"""Worker periodic maintenance tasks.

Phase 6 adds two responsibilities that the worker handles between job claims:

1. **Stale job reclaim** -- jobs whose worker died mid-execution are returned
   to the queue (or failed after ``job_max_reclaims``).
2. **Pattern decay enqueue** -- once per ``pattern_decay_interval_h`` a
   ``decay_patterns`` job is enqueued, gated by ``periodic_job_state``.

Both run idempotently: repeated calls inside the gate window are no-ops.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.core.services.job_service import reclaim_stale_jobs
from libs.core.types import JobStatus
from libs.storage.models.jobs import Job
from libs.storage.models.patterns import PeriodicJobState

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from libs.core.config import Settings

log = get_logger("worker.periodic")


def run_periodic_tasks(
    session_factory: sessionmaker,
    *,
    settings: Settings,
) -> dict[str, int]:
    """Run all periodic maintenance tasks. Returns summary counts."""
    summary: dict[str, int] = {}
    try:
        with session_factory() as session:
            counts = reclaim_stale_jobs(
                session,
                heartbeat_timeout_s=settings.job_heartbeat_timeout_s,
                max_reclaims=settings.job_max_reclaims,
            )
            summary.update(counts)
    except Exception as exc:
        log.warning("periodic.reclaim_failed", error=str(exc))

    try:
        with session_factory() as session:
            enqueued = _maybe_enqueue_decay(session, settings=settings)
            summary["decay_enqueued"] = 1 if enqueued else 0
    except Exception as exc:
        log.warning("periodic.decay_enqueue_failed", error=str(exc))
        summary["decay_enqueued"] = 0

    try:
        counts = _prune_experiment_images(keep=settings.experiment_image_max_keep)
        summary.update(counts)
    except Exception as exc:
        log.warning("periodic.image_prune_failed", error=str(exc))
        summary["images_pruned"] = 0
        summary["images_kept"] = 0

    return summary


def _prune_experiment_images(*, keep: int) -> dict[str, int]:
    """Delete oldest `synthetos-exp-*` images beyond the keep window.

    Each `execution_setup` build with a custom `build_recipe.dockerfile_content`
    produces a uniquely-tagged `synthetos-exp-<uuid7>` image and Docker never
    prunes it on its own. We keep the `keep` newest by `Created` timestamp
    and remove the rest. The orchestration images (`synthetos:latest`,
    `synthetos-web:latest`, `synthetos-experiment-runner:latest`) are
    excluded by the tag-prefix filter.

    Removals use `force=False`: an image in use by a running container
    raises `ImageInUseError` which we swallow — we never want to interrupt
    an in-flight experiment to free disk.
    """
    from docker.errors import APIError

    import docker

    client = docker.from_env()
    images = client.images.list(filters={"reference": "synthetos-exp-*"})
    images.sort(key=lambda img: img.attrs.get("Created", ""), reverse=True)

    to_keep = images[:keep]
    to_remove = images[keep:]

    pruned = 0
    for img in to_remove:
        try:
            client.images.remove(image=img.id, force=False)
            pruned += 1
        except APIError as exc:
            # In-use, deleted concurrently, etc. — leave it for the next tick.
            log.debug("periodic.image_remove_skipped", image=img.id, error=str(exc))

    return {"images_pruned": pruned, "images_kept": len(to_keep)}


def _maybe_enqueue_decay(session, *, settings: Settings) -> bool:
    """Enqueue decay_patterns if the configured interval has elapsed."""
    state = session.get(PeriodicJobState, "decay_patterns")
    now = utcnow()
    interval = timedelta(hours=settings.pattern_decay_interval_h)

    if (
        state is not None
        and state.last_enqueued_at is not None
        and (now - state.last_enqueued_at) < interval
    ):
        return False

    job = Job(
        id=uuid7(),
        cycle_id=None,
        job_type="decay_patterns",
        status=JobStatus.pending,
        payload={"max_staleness_days": settings.pattern_max_staleness_days},
        priority=0,
        created_at=now,
    )
    session.add(job)

    if state is None:
        state = PeriodicJobState(
            job_kind="decay_patterns",
            last_enqueued_at=now,
            last_job_id=job.id,
        )
        session.add(state)
    else:
        state.last_enqueued_at = now
        state.last_job_id = job.id

    session.commit()
    log.info("periodic.decay_enqueued", job_id=str(job.id))
    return True
