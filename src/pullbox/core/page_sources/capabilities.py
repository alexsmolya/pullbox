"""Runtime capability checks for the embedded comic-reader adapters."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from pullbox.core.rar_backend import RarBackendUnavailableError, configure_rarfile_backend
from pullbox.models.library import FileFormat


@dataclass(frozen=True, slots=True)
class ReaderFormatCapability:
    """One path-free format readiness result."""

    format: FileFormat
    available: bool
    detail: str


def inspect_reader_capabilities() -> tuple[ReaderFormatCapability, ...]:
    """Inspect installed parser/renderer dependencies without reading user files."""
    capabilities = [
        ReaderFormatCapability(FileFormat.CBZ, True, "ZIP reader ready"),
        _cbr_capability(),
        _cb7_capability(),
        ReaderFormatCapability(FileFormat.CBT, True, "TAR reader ready"),
        _pdf_capability(),
    ]
    return tuple(capabilities)


def _cbr_capability() -> ReaderFormatCapability:
    try:
        configure_rarfile_backend()
    except RarBackendUnavailableError:
        return ReaderFormatCapability(FileFormat.CBR, False, "Official UnRAR unavailable")
    return ReaderFormatCapability(FileFormat.CBR, True, "Official UnRAR ready")


def _cb7_capability() -> ReaderFormatCapability:
    try:
        import py7zr  # noqa: F401
    except ImportError:
        return ReaderFormatCapability(FileFormat.CB7, False, "7-Zip reader unavailable")
    return ReaderFormatCapability(FileFormat.CB7, True, "7-Zip reader ready")


def _pdf_capability() -> ReaderFormatCapability:
    try:
        import pdf2image  # noqa: F401
    except ImportError:
        return ReaderFormatCapability(FileFormat.PDF, False, "PDF renderer unavailable")
    if shutil.which("pdfinfo") is None or shutil.which("pdftoppm") is None:
        return ReaderFormatCapability(FileFormat.PDF, False, "Poppler utilities unavailable")
    return ReaderFormatCapability(FileFormat.PDF, True, "Poppler renderer ready")
