"""Library service — file statistics and comics directory management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, overload

import structlog
from sqlalchemy import func, select

from pullbox.models.config import SystemConfig
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _normalize_library_path(path: str | Path) -> str:
    """Return a normalized absolute path string for library path comparisons."""
    return str(Path(path).expanduser().resolve(strict=False))


@overload
def _rewrite_library_prefix(path_value: str, old_prefix: str, new_prefix: str) -> str: ...


@overload
def _rewrite_library_prefix(path_value: None, old_prefix: str, new_prefix: str) -> None: ...


def _rewrite_library_prefix(path_value: str | None, old_prefix: str, new_prefix: str) -> str | None:
    """Rewrite one absolute library path from an old root prefix to a new one."""
    if not path_value:
        return path_value

    normalized = _normalize_library_path(path_value)
    if normalized == old_prefix:
        return new_prefix
    if normalized.startswith(old_prefix + os.sep):
        return new_prefix + normalized[len(old_prefix) :]
    return path_value


class LibraryService:
    """Read-only library statistics and unmatched file queries."""

    @staticmethod
    async def get_unmatched(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LibraryFile]:
        """Get files in the matching queue (unmatched)."""
        result = await session.execute(
            select(LibraryFile)
            .where(LibraryFile.match_confidence == MatchConfidence.UNMATCHED)
            .order_by(LibraryFile.file_name)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_stats(session: AsyncSession) -> dict[str, int]:
        """Get library statistics."""
        total = (await session.execute(select(func.count(LibraryFile.id)))).scalar_one()

        matched = (
            await session.execute(
                select(func.count(LibraryFile.id)).where(
                    LibraryFile.match_confidence != MatchConfidence.UNMATCHED
                )
            )
        ).scalar_one()

        unmatched = total - matched

        # By format
        format_counts = {}
        for fmt in FileFormat:
            count = (
                await session.execute(
                    select(func.count(LibraryFile.id)).where(LibraryFile.file_format == fmt)
                )
            ).scalar_one()
            format_counts[fmt.value] = count

        total_size = (
            await session.execute(select(func.sum(LibraryFile.file_size)))
        ).scalar_one() or 0

        return {
            "total_files": total,
            "matched": matched,
            "unmatched": unmatched,
            "total_size_bytes": total_size,
            **format_counts,
        }


# ── Comics directory helpers ───────────────────────────────────────


async def get_comics_directory(session: AsyncSession) -> Path | None:
    """Get the configured primary comics directory, or None if not set."""
    row = await session.get(SystemConfig, "comics_directory")
    if row and row.value:
        return Path(row.value)
    return None


async def set_comics_directory(session: AsyncSession, path: Path) -> LibraryRoot:
    """Set the primary comics directory.

    Validates the path, stores it in SystemConfig, and ensures a
    LibraryRoot record exists for the path.

    Raises:
        ValueError: If the path does not exist or is not a directory.
    """
    if not path.exists():
        raise ValueError(f"Path '{path}' does not exist")
    if not path.is_dir():
        raise ValueError(f"Path '{path}' is not a directory")

    # Upsert the SystemConfig row
    row = await session.get(SystemConfig, "comics_directory")
    if row:
        row.value = str(path)
    else:
        session.add(SystemConfig(key="comics_directory", value=str(path), value_type="string"))

    # Find or create a LibraryRoot for this path
    result = await session.execute(select(LibraryRoot).where(LibraryRoot.path == str(path)))
    root = result.scalar_one_or_none()

    if root:
        root.name = "Comics Directory"
        root.enabled = True
    else:
        root = LibraryRoot(name="Comics Directory", path=str(path), enabled=True)
        session.add(root)

    await session.flush()
    return root


async def reconcile_runtime_library_paths(
    session: AsyncSession,
    runtime_root: Path,
) -> dict[str, int | str] | None:
    """Reconcile persisted library paths to the active runtime library root.

    Pullbox stores library roots, series folders, and tracked file paths as
    absolute paths. When the app moves between host-local development and a
    containerized runtime, those absolute prefixes can drift even though both
    runtimes point at the same mounted library data. This helper rewrites the
    persisted primary library prefix so health checks and filesystem operations
    continue to target the active runtime path.
    """
    runtime_root_str = _normalize_library_path(runtime_root)
    config_row = await session.get(SystemConfig, "comics_directory")
    if config_row is None or not config_row.value.strip():
        return None

    stored_root_str = _normalize_library_path(config_row.value)
    if stored_root_str == runtime_root_str:
        return None

    config_row.value = runtime_root_str

    roots = list((await session.execute(select(LibraryRoot))).scalars().all())
    old_root = next(
        (root for root in roots if _normalize_library_path(root.path) == stored_root_str),
        None,
    )
    target_root = next(
        (root for root in roots if _normalize_library_path(root.path) == runtime_root_str),
        None,
    )

    if target_root is None:
        if old_root is not None:
            old_root.path = runtime_root_str
            old_root.enabled = True
            target_root = old_root
        else:
            target_root = LibraryRoot(
                name="Comics Directory",
                path=runtime_root_str,
                enabled=True,
            )
            session.add(target_root)
            await session.flush()

    series_rows = list((await session.execute(select(Series))).scalars().all())
    library_files = list((await session.execute(select(LibraryFile))).scalars().all())

    series_updated = 0
    library_files_updated = 0
    for series in series_rows:
        next_path = _rewrite_library_prefix(series.path, stored_root_str, runtime_root_str)
        root_id_changed = False
        if (
            old_root is not None
            and target_root is not None
            and series.library_root_id == old_root.id
            and target_root.id is not None
            and series.library_root_id != target_root.id
        ):
            series.library_root_id = target_root.id
            root_id_changed = True
        if next_path != series.path:
            series.path = next_path
            series_updated += 1
        elif root_id_changed:
            series_updated += 1

    for library_file in library_files:
        next_path = _rewrite_library_prefix(
            library_file.file_path,
            stored_root_str,
            runtime_root_str,
        )
        root_id_changed = False
        if (
            old_root is not None
            and target_root is not None
            and library_file.library_root_id == old_root.id
            and target_root.id is not None
            and library_file.library_root_id != target_root.id
        ):
            library_file.library_root_id = target_root.id
            root_id_changed = True
        if next_path != library_file.file_path:
            library_file.file_path = next_path
            library_file.file_name = Path(next_path).name
            library_files_updated += 1
        elif root_id_changed:
            library_files_updated += 1

    if (
        old_root is not None
        and target_root is not None
        and old_root.id != target_root.id
        and old_root.path != runtime_root_str
    ):
        old_root.enabled = False

    await session.flush()
    return {
        "old_root": stored_root_str,
        "new_root": runtime_root_str,
        "series_updated": series_updated,
        "library_files_updated": library_files_updated,
    }
