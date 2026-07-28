from __future__ import annotations

import asyncio

import pytest

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.providers.artifact_hosts.limiter import ArtifactTransferLimiter


@pytest.mark.asyncio
async def test_host_waiter_does_not_consume_global_slot_or_block_other_host() -> None:
    limiter = ArtifactTransferLimiter(global_limit=2, per_host_limit=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    unrelated_started = asyncio.Event()

    async def run_first() -> None:
        async with limiter.slot(DirectArtifactHostKind.PIXELDRAIN):
            first_started.set()
            await release_first.wait()

    async def run_second() -> None:
        async with limiter.slot(DirectArtifactHostKind.PIXELDRAIN):
            second_started.set()

    async def run_unrelated() -> None:
        async with limiter.slot(DirectArtifactHostKind.MEGA):
            unrelated_started.set()

    first = asyncio.create_task(run_first())
    await first_started.wait()
    second = asyncio.create_task(run_second())
    unrelated = asyncio.create_task(run_unrelated())

    await asyncio.wait_for(unrelated_started.wait(), timeout=1)
    assert not second_started.is_set()

    release_first.set()
    await asyncio.gather(first, second, unrelated)
    assert second_started.is_set()


@pytest.mark.asyncio
async def test_limiter_honors_host_override_and_global_bound() -> None:
    limiter = ArtifactTransferLimiter(
        global_limit=2,
        per_host_limit=1,
        host_limits={DirectArtifactHostKind.PIXELDRAIN: 2},
    )
    active = 0
    maximum = 0
    release = asyncio.Event()
    both_started = asyncio.Event()

    async def run() -> None:
        nonlocal active, maximum
        async with limiter.slot(DirectArtifactHostKind.PIXELDRAIN):
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_started.set()
            await release.wait()
            active -= 1

    tasks = [asyncio.create_task(run()) for _ in range(3)]
    await asyncio.wait_for(both_started.wait(), timeout=1)
    assert maximum == 2
    release.set()
    await asyncio.gather(*tasks)


def test_limiter_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="Global"):
        ArtifactTransferLimiter(global_limit=0)
    with pytest.raises(ValueError, match="host"):
        ArtifactTransferLimiter(global_limit=2, per_host_limit=0)
