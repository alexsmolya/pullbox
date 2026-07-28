"""Fair global and per-host concurrency bounds for artifact transfers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from pullbox.models.direct_acquisition import DirectArtifactHostKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping


class ArtifactTransferLimiter:
    """Prevent one host's waiters from consuming unrelated global capacity."""

    def __init__(
        self,
        *,
        global_limit: int,
        per_host_limit: int = 1,
        host_limits: Mapping[DirectArtifactHostKind, int] | None = None,
    ) -> None:
        if global_limit < 1:
            raise ValueError("Global artifact transfer limit must be at least 1.")
        if per_host_limit < 1:
            raise ValueError("Default per-host transfer limit must be at least 1.")
        overrides = dict(host_limits or {})
        if any(limit < 1 for limit in overrides.values()):
            raise ValueError("Every artifact host transfer limit must be at least 1.")

        self._global = asyncio.Semaphore(global_limit)
        self._hosts = {
            host_kind: asyncio.Semaphore(overrides.get(host_kind, per_host_limit))
            for host_kind in DirectArtifactHostKind
        }

    @asynccontextmanager
    async def slot(self, host_kind: DirectArtifactHostKind) -> AsyncIterator[None]:
        """Acquire the host permit first so its queue cannot starve other hosts."""
        host = self._hosts[host_kind]
        await host.acquire()
        global_acquired = False
        try:
            await self._global.acquire()
            global_acquired = True
            yield
        finally:
            if global_acquired:
                self._global.release()
            host.release()
