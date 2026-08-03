"""Archive-backed comic-reader page source."""

from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from pullbox.core.archive import (
    ArchiveError,
    ArchiveMember,
    ArchiveReader,
    ArchiveResourceLimitError,
)
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

if TYPE_CHECKING:
    from pathlib import Path

    from pullbox.models.library import FileFormat


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
            members = self._reader.list_members()
        except ArchiveError as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not read this comic archive.",
            ) from exc
        if len(members) > limits.max_entries:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic contains too many archive entries to open safely.",
            )
        names = _validate_archive_members(members, limits)
        self._members = {member.name: member for member in members}
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
        member = self._members[descriptor.name]
        if member.size > self._limits.max_page_bytes:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic page is too large to open safely.",
            )
        try:
            data = self._reader.read_file(
                descriptor.name,
                max_bytes=self._limits.max_page_bytes,
            )
        except ArchiveResourceLimitError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic page is too large to open safely.",
            ) from exc
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
            expected_format = {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/webp": "WEBP",
                "image/gif": "GIF",
                "image/bmp": "BMP",
                "image/tiff": "TIFF",
            }.get(source_media_type)
            orientation = image.getexif().get(274, 1) if hasattr(image, "getexif") else 1
            needs_normalization = (
                source_media_type in {"image/bmp", "image/tiff"}
                or image.format != expected_format
                or orientation != 1
                or bool(getattr(image, "is_animated", False))
                or width > limits.max_rendition_width
                or height > limits.max_rendition_height
            )
            if not needs_normalization:
                image.verify()
                return PagePayload(index=index, media_type=source_media_type, data=data)

            image.seek(0)
            normalized = ImageOps.exif_transpose(image)
            try:
                normalized.thumbnail(
                    (limits.max_rendition_width, limits.max_rendition_height),
                    Image.Resampling.LANCZOS,
                )
                output = io.BytesIO()
                if source_media_type in {"image/jpeg", "image/bmp", "image/tiff"}:
                    normalized.convert("RGB").save(
                        output,
                        format="JPEG",
                        quality=88,
                        optimize=True,
                    )
                elif source_media_type == "image/png":
                    normalized.save(output, format="PNG", optimize=True)
                elif source_media_type == "image/webp":
                    normalized.save(output, format="WEBP", quality=88, method=4)
                elif source_media_type == "image/gif":
                    normalized.save(output, format="GIF", optimize=True)
                else:
                    raise PageSourceError(
                        PageSourceErrorCode.CORRUPT_SOURCE,
                        "Pullbox could not decode this comic page.",
                    )
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
    return PagePayload(
        index=index,
        media_type=_delivery_media_type(name),
        data=normalized_data,
    )


def _validate_archive_members(
    members: list[ArchiveMember],
    limits: ReaderResourceLimits,
) -> list[str]:
    """Apply format-neutral metadata budgets before extraction or decode."""
    regular_names: list[str] = []
    total_size = 0
    for member in members:
        name = member.name
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "This comic contains an unsafe archive entry.",
            )
        if (
            len(normalized) > limits.max_member_path_chars
            or len(path.parts) > limits.max_member_depth
        ):
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This comic contains an archive path beyond the configured safety limit.",
            )
        if not member.is_regular_file or member.is_link:
            continue
        size = max(0, member.size)
        total_size += size
        compressed_size = member.compressed_size
        if size > 0 and compressed_size is not None:
            compressed = max(1, int(compressed_size))
            if size / compressed > limits.max_compression_ratio:
                raise PageSourceError(
                    PageSourceErrorCode.RESOURCE_LIMIT,
                    "This comic exceeds the configured compression-ratio limit.",
                )
        regular_names.append(name)
    if total_size > limits.max_total_uncompressed_bytes:
        raise PageSourceError(
            PageSourceErrorCode.RESOURCE_LIMIT,
            "This comic expands beyond the configured safety limit.",
        )
    pages = canonical_page_names(regular_names)
    if len(pages) > limits.max_image_entries:
        raise PageSourceError(
            PageSourceErrorCode.RESOURCE_LIMIT,
            "This comic contains too many image pages to open safely.",
        )
    return pages
