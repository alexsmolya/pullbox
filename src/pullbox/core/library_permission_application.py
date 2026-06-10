"""Apply library permission policy to materialized files."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from pullbox.core.library_permission_engine import (
    PermissionAction,
    PermissionChangeResult,
    apply_permission_change,
)
from pullbox.core.library_permissions import (
    load_library_permission_policy,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.library_permissions import LibraryPermissionPolicy

logger = structlog.get_logger(__name__)


async def apply_materialized_file_permissions(
    session: AsyncSession,
    final_path: Path,
    *,
    move_to_library: bool,
    series_folder_created: bool,
    policy: LibraryPermissionPolicy | None = None,
) -> tuple[PermissionChangeResult, ...]:
    """Apply best-effort chmod policy to Pullbox-materialized library files."""
    results: list[PermissionChangeResult] = []
    if not move_to_library:
        return ()

    effective_policy = policy or await load_library_permission_policy(session)
    if not effective_policy.enabled:
        return ()

    if series_folder_created and effective_policy.apply_to_created_folders:
        folder_result = await asyncio.to_thread(
            apply_permission_change,
            final_path.parent,
            effective_policy.folder_mode,
            dry_run=False,
            skip_hardlinks=True,
            skip_symlinks=True,
        )
        log_permission_result(
            "library_folder_permission",
            folder_result,
            policy=effective_policy.serialized(),
        )
        results.append(folder_result)

    if effective_policy.apply_to_materialized_files:
        file_result = await asyncio.to_thread(
            apply_permission_change,
            final_path,
            effective_policy.file_mode,
            dry_run=False,
            skip_hardlinks=effective_policy.hardlink_behavior == "skip",
            skip_symlinks=effective_policy.symlink_behavior == "skip",
        )
        log_permission_result(
            "library_file_permission",
            file_result,
            policy=effective_policy.serialized(),
        )
        results.append(file_result)

    return tuple(results)


def log_permission_result(
    event_prefix: str,
    result: PermissionChangeResult,
    *,
    policy: dict[str, object],
) -> None:
    """Log a permission result without letting chmod failures break imports."""
    serialized = result.serialized()
    log_payload = {
        **serialized,
        "policy": policy,
    }
    action = serialized["action"]
    if action == PermissionAction.FAILED.value:
        logger.warning(f"{event_prefix}_failed", **log_payload)
        return
    if action == PermissionAction.UNSUPPORTED.value:
        logger.warning(f"{event_prefix}_unsupported", **log_payload)
        return
    logger.info(f"{event_prefix}_checked", **log_payload)
