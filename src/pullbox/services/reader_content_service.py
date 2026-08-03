"""Short-session reader source resolution and bounded revisioned page delivery."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from pullbox.core.library_root_resolution import resolve_path_inside_roots
from pullbox.core.page_sources import (
    PageSource,
    PageSourceError,
    PageSourceErrorCode,
    ReaderResourceLimits,
    open_page_source,
)
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import FileFormat, LibraryFile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_READABLE_FORMATS = frozenset(
    {FileFormat.CBZ, FileFormat.CBR, FileFormat.CB7, FileFormat.CBT, FileFormat.PDF}
)
_MEDIA_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


class StaleReaderRevisionError(Exception):
    """Raised when a page URL references a replaced source revision."""


@dataclass(frozen=True, slots=True)
class ReaderSourceRecord:
    """Database-only reader source facts detached before filesystem work."""

    issue_id: int
    issue_title: str | None
    issue_number: str
    series_title: str
    library_file_id: int
    file_path: str
    root_path: str
    file_format: FileFormat
    stored_file_hash: str | None


@dataclass(frozen=True, slots=True)
class ResolvedReaderSource:
    """Contained live source path and revision used outside a DB session."""

    issue_id: int
    issue_title: str | None
    issue_number: str
    series_title: str
    library_file_id: int
    path: Path
    file_format: FileFormat
    revision: str


@dataclass(frozen=True, slots=True)
class ReaderManifest:
    """Format-neutral manifest details produced by the content service."""

    issue_id: int
    title: str
    issue_label: str
    format: FileFormat
    page_count: int
    revision: str


@dataclass(frozen=True, slots=True)
class ReaderPageFile:
    """One immutable revisioned cache file ready for streaming."""

    path: Path
    media_type: str
    etag: str


async def load_reader_source_record(session: AsyncSession, issue_id: int) -> ReaderSourceRecord:
    """Load reader metadata only; perform no filesystem or archive work."""
    result = await session.execute(
        select(Issue)
        .options(
            joinedload(Issue.series),
            joinedload(Issue.library_file).joinedload(LibraryFile.library_root),
        )
        .where(Issue.id == issue_id)
    )
    issue = result.unique().scalar_one_or_none()
    if issue is None or issue.status is not IssueStatus.OWNED or issue.library_file is None:
        raise PageSourceError(
            PageSourceErrorCode.MISSING_FILE,
            "This issue does not have a readable downloaded file.",
        )
    library_file = issue.library_file
    if library_file.file_format not in _READABLE_FORMATS:
        raise PageSourceError(
            PageSourceErrorCode.UNSUPPORTED_FORMAT,
            "This downloaded format is not supported by the reader.",
        )
    return ReaderSourceRecord(
        issue_id=issue.id,
        issue_title=issue.title,
        issue_number=f"{issue.issue_number:g}",
        series_title=issue.series.title,
        library_file_id=library_file.id,
        file_path=library_file.file_path,
        root_path=library_file.library_root.path,
        file_format=library_file.file_format,
        stored_file_hash=library_file.file_hash,
    )


def resolve_reader_source(record: ReaderSourceRecord) -> ResolvedReaderSource:
    """Contain and stat a reader file after its database session is closed."""
    try:
        path = resolve_path_inside_roots(
            record.file_path,
            (record.root_path,),
            require_file=True,
        )
        stat = path.stat()
    except (OSError, ValueError) as exc:
        raise PageSourceError(
            PageSourceErrorCode.MISSING_FILE,
            "This downloaded file is no longer available.",
        ) from exc
    revision_input = (
        f"reader-v1:{record.library_file_id}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"{record.stored_file_hash or ''}"
    )
    revision = hashlib.sha256(revision_input.encode()).hexdigest()[:32]
    return ResolvedReaderSource(
        issue_id=record.issue_id,
        issue_title=record.issue_title,
        issue_number=record.issue_number,
        series_title=record.series_title,
        library_file_id=record.library_file_id,
        path=path,
        file_format=record.file_format,
        revision=revision,
    )


class ReaderContentService:
    """Off-event-loop page indexing/rendering with bounded source and disk caches."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        limits: ReaderResourceLimits | None = None,
        max_open_sources: int = 8,
        max_cache_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self._cache_dir = cache_dir
        self._limits = limits or ReaderResourceLimits()
        self._max_open_sources = max(1, max_open_sources)
        self._max_cache_bytes = max(1, max_cache_bytes)
        self._sources: OrderedDict[str, PageSource] = OrderedDict()
        self._source_locks: dict[str, asyncio.Lock] = {}
        self._coordination_lock = asyncio.Lock()

    async def get_manifest(self, source: ResolvedReaderSource) -> ReaderManifest:
        """Build a warm-cache-friendly manifest without retaining a DB session."""
        page_source = await self.get_page_source(source)
        title = source.issue_title or f"{source.series_title} #{source.issue_number}"
        return ReaderManifest(
            issue_id=source.issue_id,
            title=title,
            issue_label=f"{source.series_title} #{source.issue_number}",
            format=source.file_format,
            page_count=len(page_source.pages),
            revision=source.revision,
        )

    async def get_page_source(self, source: ResolvedReaderSource) -> PageSource:
        """Return one cached canonical page source, opening it once per revision."""
        lock = await self._source_lock(source.revision)
        async with lock:
            async with self._coordination_lock:
                cached = self._sources.get(source.revision)
                if cached is not None:
                    self._sources.move_to_end(source.revision)
                    return cached
            opened = await anyio.to_thread.run_sync(
                lambda: open_page_source(
                    source.path,
                    declared_format=source.file_format,
                    limits=self._limits,
                ),
                abandon_on_cancel=True,
            )
            async with self._coordination_lock:
                self._sources[source.revision] = opened
                self._sources.move_to_end(source.revision)
                while len(self._sources) > self._max_open_sources:
                    expired_revision, _ = self._sources.popitem(last=False)
                    expired_lock = self._source_locks.get(expired_revision)
                    if expired_lock is not None and not expired_lock.locked():
                        self._source_locks.pop(expired_revision, None)
            return opened

    async def get_page(
        self,
        source: ResolvedReaderSource,
        *,
        page_index: int,
        revision: str,
    ) -> ReaderPageFile:
        """Return a single-flight immutable cache file for one page."""
        if revision != source.revision:
            raise StaleReaderRevisionError
        page_source = await self.get_page_source(source)
        if page_index < 0 or page_index >= len(page_source.pages):
            raise PageSourceError(
                PageSourceErrorCode.PAGE_OUT_OF_RANGE,
                "The requested comic page is outside the available range.",
            )
        descriptor = page_source.pages[page_index]
        suffix = _MEDIA_SUFFIXES.get(descriptor.media_type, ".bin")
        target = (
            self._cache_dir / source.revision[:2] / source.revision / f"{page_index:06d}{suffix}"
        )
        etag = f'"reader-{source.revision}-{page_index}"'
        if await anyio.to_thread.run_sync(target.is_file):
            return ReaderPageFile(path=target, media_type=descriptor.media_type, etag=etag)

        lock = await self._source_lock(source.revision)
        async with lock:
            if await anyio.to_thread.run_sync(target.is_file):
                return ReaderPageFile(path=target, media_type=descriptor.media_type, etag=etag)
            payload = await anyio.to_thread.run_sync(
                page_source.read_page,
                page_index,
                abandon_on_cancel=True,
            )
            await anyio.to_thread.run_sync(
                self._write_cache_file,
                target,
                payload.data,
                abandon_on_cancel=True,
            )
        return ReaderPageFile(path=target, media_type=payload.media_type, etag=etag)

    async def _source_lock(self, revision: str) -> asyncio.Lock:
        async with self._coordination_lock:
            return self._source_locks.setdefault(revision, asyncio.Lock())

    def _write_cache_file(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".reader-page-",
                dir=target.parent,
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self._enforce_cache_budget()

    def _enforce_cache_budget(self) -> None:
        files: list[tuple[float, int, Path]] = []
        total = 0
        if not self._cache_dir.exists():
            return
        for path in self._cache_dir.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            files.append((stat.st_mtime, stat.st_size, path))
        if total <= self._max_cache_bytes:
            return
        for _mtime, size, path in sorted(files):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            total -= size
            if total <= self._max_cache_bytes:
                break
