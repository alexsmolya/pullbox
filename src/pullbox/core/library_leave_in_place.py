"""Leave-in-place file handling for library registration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from pullbox.core.library_naming import compute_target_filename, resolve_naming_issue_type
from pullbox.core.library_transfer import safe_move

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.library_policy import LibraryIngestPolicy
    from pullbox.models.issue import Issue
    from pullbox.models.library import LibraryRoot

logger = structlog.get_logger(__name__)


async def handle_leave_in_place(
    session: AsyncSession,
    source_path: Path,
    issue: Issue,
    series: object,
    root: LibraryRoot,
    ingest_policy: LibraryIngestPolicy,
    rename: bool,
) -> Path:
    """Handle leave-in-place registration, with optional rename."""
    if not rename:
        return source_path

    comics_dir = Path(root.path)
    if not str(source_path).startswith(str(comics_dir)):
        return source_path

    effective_issue_type = await resolve_naming_issue_type(session, issue)
    new_name = compute_target_filename(
        issue,
        series,
        source_path,
        ingest_policy,
        issue_type_override=effective_issue_type,
    )
    target_path = source_path.parent / new_name

    if target_path == source_path:
        return source_path

    await asyncio.to_thread(safe_move, source_path, target_path)

    logger.info(
        "file_renamed_in_place",
        source=str(source_path),
        destination=str(target_path),
    )
    return target_path
