"""Safety policy shared by every native artifact byte-transfer path."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import shutil
from collections.abc import Callable
from pathlib import Path

from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.providers.artifact_hosts.quarantine import remove_quarantine_file
from pullbox.providers.artifact_hosts.transport_contract import (
    ArtifactTransferError,
    ArtifactTransferPolicy,
)

DiskFreeProvider = Callable[[Path], int]


def validate_expected_size(size: int | None, policy: ArtifactTransferPolicy) -> None:
    """Reject invalid or policy-exceeding advertised sizes."""
    if size is not None and (size < 0 or size > policy.max_artifact_bytes):
        raise artifact_too_large_error()


def check_disk_budget(
    provider: DiskFreeProvider,
    root: Path,
    *,
    expected_size: int | None,
    existing_size: int,
    policy: ArtifactTransferPolicy,
) -> None:
    """Require room for remaining bytes plus the configured safety reserve."""
    remaining = max(0, (expected_size or 0) - existing_size)
    try:
        free = provider(root)
    except OSError as exc:
        raise ArtifactTransferError(
            code="artifact_disk_space_unavailable",
            message="Pullbox could not verify quarantine disk space.",
            failure_class=DirectArtifactFailureClass.SAFETY,
            retryable=False,
            intervention=True,
        ) from exc
    if free < remaining + policy.min_free_bytes:
        raise ArtifactTransferError(
            code="artifact_disk_space_insufficient",
            message="The direct-download quarantine does not have enough free space.",
            failure_class=DirectArtifactFailureClass.SAFETY,
            retryable=False,
            intervention=True,
        )


def parse_checksum(value: str | None) -> tuple[str, str] | None:
    """Validate and normalize a supported provider checksum."""
    if value is None:
        return None
    algorithm, separator, expected = value.strip().lower().partition(":")
    expected_lengths = {"md5": 32, "sha256": 64}
    if (
        separator != ":"
        or algorithm not in expected_lengths
        or len(expected) != expected_lengths[algorithm]
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise checksum_invalid_error()
    return algorithm, expected


async def verify_checksum(path: Path, checksum: str | None) -> None:
    """Hash a completed artifact off-loop and delete checksum mismatches."""
    parsed = parse_checksum(checksum)
    if parsed is None:
        return
    algorithm, expected = parsed
    actual = await asyncio.to_thread(_file_checksum, path, algorithm)
    if hmac.compare_digest(actual, expected):
        return
    remove_quarantine_file(path)
    raise checksum_mismatch_error()


def disk_free_bytes(path: Path) -> int:
    """Return free bytes for the filesystem containing a quarantine root."""
    return shutil.disk_usage(path).free


def artifact_too_large_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="artifact_too_large",
        message="The artifact exceeds the configured transfer size limit.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def checksum_invalid_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="artifact_checksum_invalid",
        message="The artifact provider returned an unsupported checksum.",
        failure_class=DirectArtifactFailureClass.PERMANENT_MIRROR,
        retryable=False,
        intervention=True,
    )


def checksum_mismatch_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="artifact_checksum_mismatch",
        message="The downloaded artifact did not match its expected checksum.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )


def _file_checksum(path: Path, algorithm: str) -> str:
    digest = hashlib.md5(usedforsecurity=False) if algorithm == "md5" else hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024**2):
            digest.update(chunk)
    return digest.hexdigest()
