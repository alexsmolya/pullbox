"""Safe path and file primitives for direct-download quarantine."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.providers.artifact_hosts.transport_contract import ArtifactTransferError

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO


def validate_quarantine_file(
    destination: Path,
    quarantine_root: Path,
    *,
    allow_existing: bool,
) -> Path:
    """Return a bounded target that cannot escape or traverse symlinks."""
    try:
        root = quarantine_root.resolve(strict=True)
    except OSError as exc:
        raise unsafe_quarantine_error() from exc
    if not root.is_dir() or root.is_symlink():
        raise unsafe_quarantine_error()

    candidate = destination.expanduser()
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise unsafe_quarantine_error() from exc
    if not parent.is_dir() or parent.is_symlink() or candidate.name in {"", ".", ".."}:
        raise unsafe_quarantine_error()

    safe_path = parent / candidate.name
    if safe_path.is_symlink():
        raise unsafe_quarantine_error()
    if safe_path.exists() and (not allow_existing or not safe_path.is_file()):
        raise unsafe_quarantine_error()
    return safe_path


def open_quarantine_file(path: Path, *, append: bool) -> BinaryIO:
    """Open a regular quarantine file without following a final symlink."""
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_APPEND if append else os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if not _is_regular_file(metadata.st_mode):
            os.close(descriptor)
            raise unsafe_quarantine_error()
        return os.fdopen(descriptor, "ab" if append else "wb", buffering=0)
    except ArtifactTransferError:
        raise
    except OSError as exc:
        raise ArtifactTransferError(
            code="artifact_quarantine_unwritable",
            message="Pullbox could not write to its direct-download quarantine.",
            failure_class=DirectArtifactFailureClass.SAFETY,
            retryable=False,
            intervention=True,
        ) from exc


def remove_quarantine_file(path: Path) -> None:
    """Best-effort removal that never follows a symlink."""
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


def unsafe_quarantine_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="unsafe_quarantine_destination",
        message="The artifact destination is outside its safe quarantine.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def _is_regular_file(mode: int) -> bool:
    import stat

    return stat.S_ISREG(mode)
