"""Tests for CancelToken and the per-job run context."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from uuid_utils import uuid7

from libs.core.errors import OperationCancelled, OperatorTimeout
from libs.core.run_context import (
    CancelReason,
    CancelToken,
    JobContext,
    check_cancelled,
    get_cancel_token,
    get_job_context,
    set_job_context,
)


def test_cancel_is_idempotent_first_reason_wins() -> None:
    token = CancelToken()
    assert not token.cancelled
    token.cancel(CancelReason.timeout)
    token.cancel(CancelReason.user_cancel)
    assert token.cancelled
    assert token.reason == CancelReason.timeout
    assert token.requested_at is not None


def test_raise_if_cancelled_maps_reason_to_exception() -> None:
    token = CancelToken()
    token.raise_if_cancelled()  # no-op while unset

    token.cancel(CancelReason.user_cancel)
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()

    timeout_token = CancelToken()
    timeout_token.cancel(CancelReason.timeout)
    with pytest.raises(OperatorTimeout):
        timeout_token.raise_if_cancelled()


def test_context_visible_inside_asyncio_run() -> None:
    """The worker sets the context var, then operators call asyncio.run()."""
    token = CancelToken()
    job_id = uuid7()
    ctx_token = set_job_context(JobContext(job_id=job_id, cancel_token=token))
    try:

        async def _inside() -> tuple[bool, bool]:
            ctx = get_job_context()
            return ctx is not None and ctx.job_id == job_id, get_cancel_token() is token

        job_id_ok, token_ok = asyncio.run(_inside())
        assert job_id_ok
        assert token_ok
    finally:
        set_job_context(None)
        # Restore via reset for hygiene in other tests.
        from libs.core.run_context import current_job_context

        current_job_context.reset(ctx_token)


def test_cross_thread_cancel_observed_by_wait() -> None:
    """A supervisor thread trips the token; a coroutine observes it promptly."""
    token = CancelToken()

    def _trip_later() -> None:
        time.sleep(0.1)
        token.cancel(CancelReason.user_cancel)

    thread = threading.Thread(target=_trip_later)

    async def _wait_for_cancel() -> float:
        start = time.monotonic()
        thread.start()
        await token.wait(poll_interval_s=0.02)
        return time.monotonic() - start

    elapsed = asyncio.run(_wait_for_cancel())
    thread.join()
    assert token.cancelled
    assert elapsed < 2.0


def test_check_cancelled_noop_without_context() -> None:
    assert get_job_context() is None
    check_cancelled()  # must not raise


def test_check_cancelled_raises_with_tripped_token() -> None:
    token = CancelToken()
    token.cancel(CancelReason.user_cancel)
    ctx_token = set_job_context(JobContext(cancel_token=token))
    try:
        with pytest.raises(OperationCancelled):
            check_cancelled()
    finally:
        from libs.core.run_context import current_job_context

        current_job_context.reset(ctx_token)
