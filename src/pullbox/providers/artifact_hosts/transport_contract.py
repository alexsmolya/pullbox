"""Shared durable-safe contracts for artifact byte transfers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.models.direct_acquisition import DirectArtifactFailureClass

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArtifactTransferPolicy:
    """Bounded runtime policy applied to every native HTTP transfer."""

    max_artifact_bytes: int = 10 * 1024**4
    min_free_bytes: int = 256 * 1024**2
    chunk_size_bytes: int = 1024**2
    idle_timeout_seconds: float = 60.0
    total_timeout_seconds: float = 24 * 60 * 60.0
    max_redirects: int = 5
    progress_interval_seconds: float = 0.5
    progress_bytes: int = 8 * 1024**2

    def __post_init__(self) -> None:
        if self.max_artifact_bytes <= 0:
            raise ValueError("Maximum artifact size must be positive.")
        if self.min_free_bytes < 0:
            raise ValueError("Minimum free disk space cannot be negative.")
        if self.chunk_size_bytes <= 0:
            raise ValueError("Transfer chunk size must be positive.")
        if self.idle_timeout_seconds <= 0 or self.total_timeout_seconds <= 0:
            raise ValueError("Transfer timeouts must be positive.")
        if self.max_redirects < 0:
            raise ValueError("Redirect limit cannot be negative.")
        if self.progress_interval_seconds < 0 or self.progress_bytes <= 0:
            raise ValueError("Progress coalescing values are invalid.")


@dataclass(frozen=True, slots=True)
class HttpTransferCheckpoint:
    """Persistable identity and byte state for one partial HTTP transfer."""

    bytes_transferred: int
    expected_size: int | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class TransferProgressSnapshot:
    """One redacted progress update suitable for durable coalescing."""

    bytes_transferred: int
    total_bytes: int | None
    percent: int | None
    bytes_per_second: float | None
    eta_seconds: float | None


@dataclass(frozen=True, slots=True)
class ArtifactTransferResult:
    """Validated byte-transfer result before archive inspection."""

    path: Path
    bytes_transferred: int
    expected_size: int | None
    etag: str | None
    last_modified: str | None
    filename_hint: str | None
    resumed: bool


class ArtifactTransferError(RuntimeError):
    """Classified transfer failure with no URL or credential context."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        failure_class: DirectArtifactFailureClass,
        retryable: bool,
        intervention: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failure_class = failure_class
        self.retryable = retryable
        self.intervention = intervention

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"failure_class={self.failure_class.value!r}, "
            f"retryable={self.retryable!r}, intervention={self.intervention!r})"
        )


class ArtifactTransferCancelledError(ArtifactTransferError):
    """Explicit user cancellation; partial bytes are deleted."""

    def __init__(self) -> None:
        super().__init__(
            code="artifact_transfer_cancelled",
            message="The artifact transfer was cancelled.",
            failure_class=DirectArtifactFailureClass.USER_ACTION,
            retryable=False,
            intervention=False,
        )


class ArtifactTransferPausedError(ArtifactTransferError):
    """Explicit user pause; a safe checkpoint remains in quarantine."""

    def __init__(self, checkpoint: HttpTransferCheckpoint) -> None:
        super().__init__(
            code="artifact_transfer_paused",
            message="The artifact transfer was paused.",
            failure_class=DirectArtifactFailureClass.USER_ACTION,
            retryable=True,
            intervention=False,
        )
        self.checkpoint = checkpoint
