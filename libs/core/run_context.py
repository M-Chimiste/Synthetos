"""Per-job run context: cancellation token and job identity.

The worker sets :data:`current_job_context` in its main thread before
dispatching an operator. Operators call ``asyncio.run(...)`` in that same
thread, and ``asyncio.run`` copies the current context, so the context var is
visible inside operator event loops without threading anything through
operator signatures.

Cancellation crosses threads: the job supervisor (heartbeat) thread trips the
token's ``threading.Event``; coroutines in the operator's event loop observe
it via :meth:`CancelToken.wait` or cooperative :func:`check_cancelled` calls.
"""

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from libs.core.clock import utcnow
from libs.core.errors import OperationCancelled, OperatorTimeout


class CancelReason(StrEnum):
    user_cancel = "user_cancel"
    timeout = "timeout"


class CancelToken:
    """Thread-safe, one-shot cancellation signal. First reason wins."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self.reason: CancelReason | None = None
        self.requested_at: datetime | None = None

    def cancel(self, reason: CancelReason = CancelReason.user_cancel) -> None:
        """Trip the token. Idempotent; the first recorded reason is kept."""
        with self._lock:
            if not self._event.is_set():
                self.reason = reason
                self.requested_at = utcnow()
                self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise the reason-appropriate exception if the token is set."""
        if not self._event.is_set():
            return
        if self.reason == CancelReason.timeout:
            raise OperatorTimeout("job wall-clock deadline exceeded")
        raise OperationCancelled("job cancellation requested")

    async def wait(self, poll_interval_s: float = 0.5) -> None:
        """Resolve once the token trips.

        threading.Event has no async interface, so this polls cheaply. Used
        as the watcher side of an ``asyncio.wait(FIRST_COMPLETED)`` race
        against an in-flight LLM call.
        """
        while not self._event.is_set():
            await asyncio.sleep(poll_interval_s)


@dataclass(frozen=True)
class JobContext:
    """Identity and control surface for the currently executing job."""

    job_id: UUID | None = None
    cycle_id: UUID | None = None
    cancel_token: CancelToken | None = None


current_job_context: ContextVar[JobContext | None] = ContextVar("current_job_context", default=None)


def get_job_context() -> JobContext | None:
    return current_job_context.get()


def set_job_context(ctx: JobContext | None) -> Token[JobContext | None]:
    """Set the context var; callers must reset with the returned token."""
    return current_job_context.set(ctx)


def get_cancel_token() -> CancelToken | None:
    ctx = current_job_context.get()
    return ctx.cancel_token if ctx is not None else None


def check_cancelled() -> None:
    """Cooperative checkpoint: raise if the current job was cancelled.

    No-op when no job context is set (API process, tests).
    """
    token = get_cancel_token()
    if token is not None:
        token.raise_if_cancelled()
