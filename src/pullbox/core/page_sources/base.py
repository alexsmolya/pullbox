"""Shared contracts and validation for comic-reader page sources."""

from __future__ import annotations

import re
import tarfile
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol

from pullbox.models.library import FileFormat

_IMAGE_MEDIA_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
_NATURAL_PARTS = re.compile(r"(\d+)")


class PageSourceErrorCode(StrEnum):
    """Stable safe failure codes returned by the reader boundary."""

    MISSING_FILE = "missing_file"
    UNSUPPORTED_FORMAT = "unsupported_format"
    FORMAT_MISMATCH = "format_mismatch"
    CORRUPT_SOURCE = "corrupt_source"
    EMPTY_SOURCE = "empty_source"
    PAGE_OUT_OF_RANGE = "page_out_of_range"
    RESOURCE_LIMIT = "resource_limit"
    RENDERER_UNAVAILABLE = "renderer_unavailable"


class PageSourceError(Exception):
    """Safe reader page-source failure with a stable public code."""

    def __init__(self, code: PageSourceErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ReaderResourceLimits:
    """Per-source safety budgets applied before and during page access."""

    max_entries: int = 10_000
    max_page_bytes: int = 128 * 1024 * 1024
    max_total_uncompressed_bytes: int = 4 * 1024 * 1024 * 1024
    max_compression_ratio: int = 250
    max_image_pixels: int = 80_000_000
    max_image_entries: int = 5_000
    max_member_path_chars: int = 1_024
    max_member_depth: int = 32
    max_rendition_width: int = 2_560
    max_rendition_height: int = 4_096
    pdf_dpi: int = 160
    render_timeout_seconds: int = 30


@dataclass(frozen=True, slots=True)
class PageDescriptor:
    """One canonical zero-based page in a comic source."""

    index: int
    name: str
    media_type: str


@dataclass(frozen=True, slots=True)
class PagePayload:
    """Bounded bytes for one browser-renderable page."""

    index: int
    media_type: str
    data: bytes


class PageSource(Protocol):
    """Format-neutral synchronous page source.

    Callers must offload construction and reads from the event loop.
    """

    path: Path
    format: FileFormat
    pages: tuple[PageDescriptor, ...]

    def read_page(self, index: int) -> PagePayload: ...


def media_type_for_name(name: str) -> str | None:
    """Return the browser media type for a supported image member."""
    return _IMAGE_MEDIA_TYPES.get(PurePosixPath(name).suffix.lower())


def canonical_page_names(names: list[str]) -> list[str]:
    """Filter unsafe/non-page members and return deterministic natural order."""
    pages: list[str] = []
    for raw_name in names:
        normalized = raw_name.replace("\\", "/")
        member = PurePosixPath(normalized)
        if member.is_absolute() or not member.parts or ".." in member.parts:
            continue
        if any(part == "__MACOSX" or part.startswith(".") for part in member.parts):
            continue
        if media_type_for_name(normalized) is None:
            continue
        pages.append(normalized)
    return sorted(pages, key=_natural_path_key)


def _natural_path_key(value: str) -> tuple[tuple[int, int | str, int], ...]:
    parts: list[tuple[int, int | str, int]] = []
    normalized = unicodedata.normalize("NFC", value).casefold()
    for part in _NATURAL_PARTS.split(normalized):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part), len(part)))
        else:
            parts.append((1, part, 0))
    return tuple(parts)


def detect_comic_format(path: Path) -> FileFormat:
    """Detect a supported comic container by signature, never extension alone."""
    if not path.is_file():
        raise PageSourceError(PageSourceErrorCode.MISSING_FILE, "The comic file is unavailable.")
    try:
        with path.open("rb") as source:
            signature = source.read(16)
    except OSError as exc:
        raise PageSourceError(
            PageSourceErrorCode.MISSING_FILE,
            "The comic file could not be opened.",
        ) from exc

    if signature.startswith(b"PK\x03\x04"):
        return FileFormat.CBZ
    if signature.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return FileFormat.CBR
    if signature.startswith(b"7z\xbc\xaf\x27\x1c"):
        return FileFormat.CB7
    if signature.startswith(b"%PDF-"):
        return FileFormat.PDF
    try:
        if tarfile.is_tarfile(path):
            return FileFormat.CBT
    except OSError:
        pass
    raise PageSourceError(
        PageSourceErrorCode.UNSUPPORTED_FORMAT,
        "Pullbox could not identify this comic format.",
    )


def validate_page_index(index: int, page_count: int) -> None:
    """Require a zero-based page index inside the canonical page range."""
    if index < 0 or index >= page_count:
        raise PageSourceError(
            PageSourceErrorCode.PAGE_OUT_OF_RANGE,
            "The requested comic page is outside the available range.",
        )
