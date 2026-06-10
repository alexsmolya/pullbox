"""Library target path planning helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pullbox.core.exceptions import ConfigurationError
from pullbox.core.library_naming import (
    build_series_folder_name,
    compute_target_filename,
    resolve_naming_issue_type,
)
from pullbox.models.series import Series

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.library_policy import LibraryIngestPolicy
    from pullbox.models.issue import Issue
    from pullbox.models.library import LibraryRoot


@dataclass(frozen=True, slots=True)
class ResolvedLibraryTarget:
    """Resolved destination path plus folder-creation metadata."""

    path: Path
    series_folder_created: bool


async def resolve_library_target_path(
    session: AsyncSession,
    source_path: Path,
    issue: Issue,
    series: object,
    root: LibraryRoot,
    ingest_policy: LibraryIngestPolicy,
    rename: bool,
) -> ResolvedLibraryTarget:
    """Resolve the final library path before materializing the artifact."""
    target_path = await predict_library_target_path(
        session,
        source_path,
        issue,
        series,
        root,
        ingest_policy,
        rename,
    )
    series_folder = target_path.parent

    comics_dir = Path(root.path)
    if not comics_dir.exists():
        raise ConfigurationError(f"Comics directory does not exist: {comics_dir}")

    series_folder_created = not series_folder.exists()
    await asyncio.to_thread(series_folder.mkdir, parents=True, exist_ok=True)

    if target_path.exists() and target_path != source_path:
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 1
        while target_path.exists():
            target_path = series_folder / f"{stem} ({counter}){suffix}"
            counter += 1

    return ResolvedLibraryTarget(
        path=target_path,
        series_folder_created=series_folder_created,
    )


async def predict_library_target_path(
    session: AsyncSession,
    source_path: Path,
    issue: Issue,
    series: object,
    root: LibraryRoot,
    ingest_policy: LibraryIngestPolicy,
    rename: bool,
) -> Path:
    """Compute the canonical library target path without applying collision suffixes."""
    comics_dir = Path(root.path)
    if not comics_dir.exists():
        raise ConfigurationError(f"Comics directory does not exist: {comics_dir}")

    if isinstance(series, Series) and series.path:
        series_folder = Path(series.path)
    else:
        folder_name = build_series_folder_name(series, ingest_policy)
        series_folder = comics_dir / folder_name

    if rename:
        effective_issue_type = await resolve_naming_issue_type(session, issue)
        target_name = compute_target_filename(
            issue,
            series,
            source_path,
            ingest_policy,
            issue_type_override=effective_issue_type,
        )
    else:
        target_name = source_path.name

    return series_folder / target_name
