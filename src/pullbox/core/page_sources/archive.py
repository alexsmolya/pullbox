"""Archive-backed comic-reader page source."""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from pullbox.core.archive import ArchiveError, ArchiveReader
from pullbox.core.page_sources.base import (
    PageDescriptor,
    PagePayload,
    PageSourceError,
    PageSourceErrorCode,
    ReaderResourceLimits,
    canonical_page_names,
    media_type_for_name,
    validate_page_index,
)
from pullbox.models.library import FileFormat

if TYPE_CHECKING:
    from pathlib import Path


class ArchivePageSource:
    """Canonical bounded pages from CBZ, CBR, CB7, or CBT."""

    def __init__(
        self,
        path: Path,
        format_: FileFormat,
        limits: ReaderResourceLimits,
    ) -> None:
        self.path = path
        self.format = format_
        self._limits = limits
        self._reader = ArchiveReader(path)
        try:
            entries = self._reader.list_files()
        except ArchiveError as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not read this comic archive.",
            ) from exc
        if len(entries) > limits.max_entries:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic contains too many archive entries to open safely.",
            )
        if format_ is FileFormat.CBZ:
            _validate_zip_budgets(path, limits)
        names = canonical_page_names(entries)
        if not names:
            raise PageSourceError(
                PageSourceErrorCode.EMPTY_SOURCE,
                "Pullbox could not find readable pages in this file.",
            )
        self.pages = tuple(
            PageDescriptor(index=index, name=name, media_type=_delivery_media_type(name))
            for index, name in enumerate(names)
        )

    def read_page(self, index: int) -> PagePayload:
        validate_page_index(index, len(self.pages))
        descriptor = self.pages[index]
        try:
            data = self._reader.read_file(descriptor.name)
        except ArchiveError as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not read this comic page.",
            ) from exc
        if len(data) > self._limits.max_page_bytes:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic page is too large to open safely.",
            )
        return _prepare_image_payload(
            index=index,
            name=descriptor.name,
            data=data,
            limits=self._limits,
        )


def _delivery_media_type(name: str) -> str:
    media_type = media_type_for_name(name) or "application/octet-stream"
    if media_type in {"image/bmp", "image/tiff"}:
        return "image/jpeg"
    return media_type


def _prepare_image_payload(
    *,
    index: int,
    name: str,
    data: bytes,
    limits: ReaderResourceLimits,
) -> PagePayload:
    """Validate image dimensions and normalize non-baseline browser formats."""
    source_media_type = media_type_for_name(name) or "application/octet-stream"
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width * height > limits.max_image_pixels:
                raise PageSourceError(
                    PageSourceErrorCode.RESOURCE_LIMIT,
                    "This comic page has too many pixels to open safely.",
                )
            if source_media_type not in {"image/bmp", "image/tiff"}:
                image.verify()
                return PagePayload(index=index, media_type=source_media_type, data=data)

            normalized = ImageOps.exif_transpose(image).convert("RGB")
            try:
                output = io.BytesIO()
                normalized.save(output, format="JPEG", quality=88, optimize=True)
                normalized_data = output.getvalue()
            finally:
                normalized.close()
    except PageSourceError:
        raise
    except Image.DecompressionBombError as exc:
        raise PageSourceError(
            PageSourceErrorCode.RESOURCE_LIMIT,
            "This comic page has too many pixels to open safely.",
        ) from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise PageSourceError(
            PageSourceErrorCode.CORRUPT_SOURCE,
            "Pullbox could not decode this comic page.",
        ) from exc
    if len(normalized_data) > limits.max_page_bytes:
        raise PageSourceError(
            PageSourceErrorCode.RESOURCE_LIMIT,
            "This normalized comic page is too large to open safely.",
        )
    return PagePayload(index=index, media_type="image/jpeg", data=normalized_data)


def _validate_zip_budgets(path: Path, limits: ReaderResourceLimits) -> None:
    """Reject oversized or extreme-ratio ZIP members before any page read."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise PageSourceError(
            PageSourceErrorCode.CORRUPT_SOURCE,
            "Pullbox could not read this comic archive.",
        ) from exc
    total_size = sum(info.file_size for info in infos)
    if total_size > limits.max_total_uncompressed_bytes:
        raise PageSourceError(
            PageSourceErrorCode.RESOURCE_LIMIT,
            "This comic expands beyond the configured safety limit.",
        )
    for info in infos:
        if info.file_size <= 0:
            continue
        compressed = max(info.compress_size, 1)
        if info.file_size / compressed > limits.max_compression_ratio:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic exceeds the configured compression-ratio limit.",
            )
