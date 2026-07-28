"""Native artifact-host resolution and transfer contracts."""

from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostAdapter,
    ArtifactHostResolutionError,
    ArtifactTransferProtocol,
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.mega import MegaArtifactHostAdapter, MegaBridgeRunner
from pullbox.providers.artifact_hosts.resolver import ArtifactHostResolver

__all__ = [
    "ArtifactHostAdapter",
    "ArtifactHostResolutionError",
    "ArtifactHostResolver",
    "ArtifactTransferProtocol",
    "HostResolutionRequest",
    "MegaArtifactHostAdapter",
    "MegaBridgeRunner",
    "ResolvedTransfer",
]
