"""Single-page PDF rasterization for the comic reader."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from pullbox.core.page_sources.base import (
    PageDescriptor,
    PagePayload,
    PageSourceError,
    PageSourceErrorCode,
    ReaderResourceLimits,
    validate_page_index,
)
from pullbox.models.library import FileFormat

if TYPE_CHECKING:
    from pathlib import Path


class PdfPageSource:
    """Bounded one-request-at-a-time PDF page source."""

    def __init__(self, path: Path, limits: ReaderResourceLimits) -> None:
        self.path = path
        self.format = FileFormat.PDF
        self._limits = limits
        try:
            from pdf2image import pdfinfo_from_path
            from pdf2image.exceptions import (
                PDFInfoNotInstalledError,
                PDFPageCountError,
                PDFPopplerTimeoutError,
            )
        except ImportError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RENDERER_UNAVAILABLE,
                "PDF rendering is unavailable on this Pullbox server.",
            ) from exc
        try:
            raw_count = pdfinfo_from_path(
                str(path),
                timeout=limits.render_timeout_seconds,
            ).get("Pages", 0)
            page_count = int(raw_count)
        except PDFInfoNotInstalledError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RENDERER_UNAVAILABLE,
                "PDF rendering is unavailable on this Pullbox server.",
            ) from exc
        except PDFPopplerTimeoutError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This PDF took too long to inspect safely.",
            ) from exc
        except PDFPageCountError as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not read this PDF.",
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not read this PDF.",
            ) from exc
        if page_count <= 0:
            raise PageSourceError(
                PageSourceErrorCode.EMPTY_SOURCE,
                "Pullbox could not find readable pages in this PDF.",
            )
        if page_count > limits.max_entries:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This PDF contains too many pages to open safely.",
            )
        self.pages = tuple(
            PageDescriptor(index=index, name=f"page-{index + 1}", media_type="image/jpeg")
            for index in range(page_count)
        )

    def read_page(self, index: int) -> PagePayload:
        validate_page_index(index, len(self.pages))
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import (
                PDFInfoNotInstalledError,
                PDFPageCountError,
                PDFPopplerTimeoutError,
                PDFSyntaxError,
            )
        except ImportError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RENDERER_UNAVAILABLE,
                "PDF rendering is unavailable on this Pullbox server.",
            ) from exc
        page_number = index + 1
        try:
            rendered = convert_from_path(
                str(self.path),
                dpi=self._limits.pdf_dpi,
                first_page=page_number,
                last_page=page_number,
                fmt="jpeg",
                thread_count=1,
                size=max(self._limits.max_rendition_width, self._limits.max_rendition_height),
                timeout=self._limits.render_timeout_seconds,
            )
        except PDFInfoNotInstalledError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RENDERER_UNAVAILABLE,
                "PDF rendering is unavailable on this Pullbox server.",
            ) from exc
        except PDFPopplerTimeoutError as exc:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This PDF page took too long to render safely.",
            ) from exc
        except (PDFPageCountError, PDFSyntaxError) as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not render this PDF page.",
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not render this PDF page.",
            ) from exc
        if len(rendered) != 1:
            raise PageSourceError(
                PageSourceErrorCode.CORRUPT_SOURCE,
                "Pullbox could not render this PDF page.",
            )
        image = rendered[0]
        output = io.BytesIO()
        try:
            width, height = image.size
            if width * height > self._limits.max_image_pixels:
                raise PageSourceError(
                    PageSourceErrorCode.RESOURCE_LIMIT,
                    "This rendered PDF page has too many pixels to open safely.",
                )
            if (
                width > self._limits.max_rendition_width
                or height > self._limits.max_rendition_height
            ):
                image.thumbnail(
                    (
                        self._limits.max_rendition_width,
                        self._limits.max_rendition_height,
                    )
                )
            image.save(output, format="JPEG", quality=88, optimize=True)
        finally:
            image.close()
        data = output.getvalue()
        if len(data) > self._limits.max_page_bytes:
            raise PageSourceError(
                PageSourceErrorCode.RESOURCE_LIMIT,
                "This rendered PDF page is too large to open safely.",
            )
        return PagePayload(index=index, media_type="image/jpeg", data=data)
