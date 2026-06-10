"""Tests for the per-endpoint concurrency limiter."""

from __future__ import annotations

import asyncio

from libs.adapters.llm.concurrency import EndpointLimiter, get_endpoint_limiter


def test_limiter_serializes_with_max_concurrent_one() -> None:
    limiter = EndpointLimiter()
    in_flight = 0
    max_in_flight = 0

    async def call() -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.limit("http://local.test/v1", 1):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    async def main() -> None:
        await asyncio.gather(*(call() for _ in range(5)))

    asyncio.run(main())
    assert max_in_flight == 1


def test_limiter_allows_capacity_in_parallel() -> None:
    limiter = EndpointLimiter()
    in_flight = 0
    max_in_flight = 0

    async def call() -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.limit("http://local.test/v1", 3):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    async def main() -> None:
        await asyncio.gather(*(call() for _ in range(6)))

    asyncio.run(main())
    assert max_in_flight == 3


def test_limiter_keys_are_independent() -> None:
    limiter = EndpointLimiter()
    max_in_flight = 0
    in_flight = 0

    async def call(key: str) -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.limit(key, 1):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    async def main() -> None:
        await asyncio.gather(call("http://a.test"), call("http://b.test"))

    asyncio.run(main())
    assert max_in_flight == 2  # different endpoints don't contend


def test_limiter_survives_separate_asyncio_run_loops() -> None:
    """Each asyncio.run() gets a fresh loop; the limiter must not leak loop state."""
    limiter = EndpointLimiter()

    async def one_call() -> str:
        async with limiter.limit("http://local.test/v1", 1):
            return "ok"

    assert asyncio.run(one_call()) == "ok"
    assert asyncio.run(one_call()) == "ok"  # would deadlock if loop-bound state leaked


def test_limiter_capacity_change_rebuilds_semaphore() -> None:
    limiter = EndpointLimiter()
    max_in_flight = 0
    in_flight = 0

    async def call(capacity: int) -> None:
        nonlocal in_flight, max_in_flight
        async with limiter.limit("http://local.test/v1", capacity):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1

    async def main() -> None:
        # First use capacity 1 sequentially, then 2 concurrently.
        await call(1)
        await asyncio.gather(call(2), call(2))

    asyncio.run(main())
    assert max_in_flight == 2


def test_none_key_is_unlimited() -> None:
    limiter = EndpointLimiter()

    async def main() -> str:
        async with limiter.limit(None, 1):
            return "ok"

    assert asyncio.run(main()) == "ok"


def test_singleton_identity() -> None:
    assert get_endpoint_limiter() is get_endpoint_limiter()
