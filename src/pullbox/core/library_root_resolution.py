"""Library root selection helpers for file registration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from pullbox.core.exceptions import ConfigurationError
from pullbox.models.config import SystemConfig
from pullbox.models.library import LibraryRoot
from pullbox.models.series import Series

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_library_root(
    session: AsyncSession,
    source_path: Path,
    explicit_root_id: int | None,
    *,
    series: Series | None = None,
) -> LibraryRoot:
    """Resolve the LibraryRoot for file registration."""
    if explicit_root_id is not None:
        root = await session.get(LibraryRoot, explicit_root_id)
        if root is not None:
            return root

    if series is not None:
        if series.library_root_id is not None:
            root = await session.get(LibraryRoot, series.library_root_id)
            if root is not None:
                return root
        if series.path:
            series_path = str(Path(series.path).expanduser().resolve(strict=False))
            roots_result = await session.execute(
                select(LibraryRoot).where(LibraryRoot.enabled.is_(True))
            )
            for root in roots_result.scalars().all():
                root_path = str(Path(root.path).expanduser().resolve(strict=False))
                if series_path == root_path or series_path.startswith(root_path + os.sep):
                    return root

    roots_result = await session.execute(select(LibraryRoot).where(LibraryRoot.enabled.is_(True)))
    roots = list(roots_result.scalars().all())
    source_str = str(source_path)
    for root in roots:
        if source_str.startswith(root.path + "/") or source_str.startswith(root.path + "\\"):
            return root

    config_result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "comics_directory")
    )
    config = config_result.scalars().first()
    if config is not None:
        root_result = await session.execute(
            select(LibraryRoot).where(LibraryRoot.path == config.value)
        )
        root = root_result.scalars().first()
        if root is not None:
            return root

    if roots:
        return roots[0]

    raise ConfigurationError("No comics directory configured. Set it in Settings → Media.")


def path_is_inside_root(path: Path, root: LibraryRoot) -> bool:
    """Return true when a candidate path is inside a library root."""
    root_path = Path(root.path).expanduser().resolve(strict=False)
    candidate = path.expanduser().resolve(strict=False)
    return candidate == root_path or candidate.is_relative_to(root_path)


def resolve_path_inside_roots(
    path: str | Path,
    roots: Iterable[str | Path],
    *,
    require_exists: bool = False,
    require_file: bool = False,
    require_dir: bool = False,
) -> Path:
    """Resolve a path and require it to stay inside one of the supplied roots."""
    root_paths = tuple(Path(root).expanduser().resolve(strict=False) for root in roots)
    if not root_paths:
        raise ValueError("No allowed roots are configured.")

    # This is the central path validator; the candidate is immediately checked
    # against enabled library roots before any caller can use the result.
    # codeql[py/path-injection]
    candidate = Path(path).expanduser().resolve(strict=False)
    if not any(candidate == root or candidate.is_relative_to(root) for root in root_paths):
        raise ValueError(f"Selected path is outside enabled library roots: {path}")

    if require_exists and not candidate.exists():
        raise ValueError(f"Selected path does not exist: {path}")
    if require_file and not candidate.is_file():
        raise ValueError(f"Selected path is not a file: {path}")
    if require_dir and not candidate.is_dir():
        raise ValueError(f"Selected path is not a directory: {path}")

    return candidate


def materialize_series_path(series: object, series_folder: Path, root: LibraryRoot) -> None:
    """Persist the actual library folder once the first file lands there."""
    if not isinstance(series, Series):
        return
    if not series.path:
        series.path = str(series_folder)
    if series.library_root_id is None:
        series.library_root_id = root.id
