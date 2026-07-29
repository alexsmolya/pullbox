"""Closed dispatch for native artifact-host adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    HostResolutionRequest,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from pullbox.models.direct_acquisition import DirectArtifactHostKind
    from pullbox.providers.artifact_hosts.contract import (
        ArtifactHostAdapter,
        ArtifactResolutionProgressCallback,
        ResolvedTransfer,
    )


class ArtifactHostResolver:
    """Dispatch requests only to an explicitly registered native adapter."""

    def __init__(self, adapters: Iterable[ArtifactHostAdapter]) -> None:
        self._adapters: dict[DirectArtifactHostKind, ArtifactHostAdapter] = {}
        for adapter in adapters:
            if adapter.host_kind in self._adapters:
                raise ValueError(f"duplicate artifact-host adapter: {adapter.host_kind.value}")
            self._adapters[adapter.host_kind] = adapter

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Mapping[str, str],
        progress_callback: ArtifactResolutionProgressCallback | None = None,
    ) -> ResolvedTransfer:
        adapter = self._adapters.get(request.host_kind)
        if adapter is None:
            raise ArtifactHostResolutionError(
                code="unsupported_artifact_host",
                message="No native adapter is registered for this artifact host.",
                failure_class=DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST,
                retryable=False,
                intervention=True,
            )
        transfer = await adapter.resolve(
            request,
            credentials=credentials,
            progress_callback=progress_callback,
        )
        if transfer.host_kind is not request.host_kind:
            raise ArtifactHostResolutionError(
                code="artifact_host_kind_mismatch",
                message="The adapter returned a transfer for a different artifact host.",
                failure_class=DirectArtifactFailureClass.CANDIDATE_INVALID,
                retryable=False,
                intervention=True,
            )
        return transfer
