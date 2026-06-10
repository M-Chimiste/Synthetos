"""Per-endpoint concurrency limiting for LLM requests.

A single local inference server saturates quickly: operators fan out 4+
concurrent structured calls, each potentially taking 15+ minutes, and the
server's queue compounds the latency until requests start timing out. The
limiter caps in-flight HTTP requests per endpoint (base_url) regardless of
which operator or semaphore spawned them.

asyncio primitives are loop-bound and operators create a fresh event loop per
``asyncio.run()``, so semaphores are stored per (event loop -> endpoint key)
in a WeakKeyDictionary. The worker runs one job (and thus one live loop) at a
time, so this correctly caps in-flight requests per endpoint for the process.

Cross-process limits (worker + API hitting the same vLLM) are explicitly OUT
OF SCOPE for a single-user system; the inference server's own request queue
is the backstop.
"""

from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_LOCAL_MAX_CONCURRENT = 2
DEFAULT_HOSTED_MAX_CONCURRENT = 4


class EndpointLimiter:
    """Caps concurrent requests per endpoint key across one process."""

    def __init__(self) -> None:
        # loop -> endpoint key -> (semaphore, capacity). Capacity is stored so
        # a config change (new max_concurrent) rebuilds the semaphore instead
        # of silently keeping the old limit.
        self._by_loop: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, dict[str, tuple[asyncio.Semaphore, int]]
        ] = weakref.WeakKeyDictionary()

    def _semaphore(self, key: str, max_concurrent: int) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        per_loop = self._by_loop.setdefault(loop, {})
        entry = per_loop.get(key)
        if entry is None or entry[1] != max_concurrent:
            entry = (asyncio.Semaphore(max_concurrent), max_concurrent)
            per_loop[key] = entry
        return entry[0]

    @asynccontextmanager
    async def limit(self, key: str | None, max_concurrent: int) -> AsyncIterator[None]:
        """Hold one slot for the endpoint while the request is in flight."""
        if key is None or max_concurrent <= 0:
            yield
            return
        semaphore = self._semaphore(key, max_concurrent)
        async with semaphore:
            yield


_limiter = EndpointLimiter()


def get_endpoint_limiter() -> EndpointLimiter:
    """Module-level singleton: routers are built per-operator, limits are not."""
    return _limiter
