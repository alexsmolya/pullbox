"""Runtime settings helpers for import workflows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select as sa_select

from pullbox.core.file_safety import get_allowed_extensions
from pullbox.core.library_permissions import load_library_permission_policy
from pullbox.core.library_policy import (
    library_ingest_policy_from_snapshot,
    load_library_ingest_policy,
)
from pullbox.models.config import SystemConfig
from pullbox.utilities.settings import resolve_utility_directory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.config import PullboxSettings
    from pullbox.core.library_permissions import LibraryPermissionPolicy
    from pullbox.core.library_policy import LibraryIngestPolicy


@dataclass(slots=True)
class ImportRuntimeCache:
    """Per-job cached settings and ComicInfo metadata used during import execution."""

    media_settings: dict[str, str] | None = None
    trash_dir: Path | None = None
    ingest_policy: LibraryIngestPolicy | None = None
    permission_policy: LibraryPermissionPolicy | None = None
    comicinfo_payloads: dict[tuple[int, str | None], dict[str, Any]] = field(default_factory=dict)
    comicinfo_payload_timings: dict[tuple[int, str | None], dict[str, Any]] = field(
        default_factory=dict
    )


async def maybe_debug_sleep(settings: PullboxSettings, delay_seconds: float) -> None:
    """Apply an env-gated debug delay without affecting normal runtime."""
    if not settings.import_debug_slow_mode:
        return

    delay = max(float(delay_seconds), 0.0)
    if delay <= 0:
        return

    await asyncio.sleep(delay)


async def maybe_slow_phase_delay(settings: PullboxSettings) -> None:
    """Slow phase-level progress transitions in dev when enabled."""
    await maybe_debug_sleep(settings, settings.import_debug_phase_delay_seconds)


async def maybe_slow_item_delay(settings: PullboxSettings) -> None:
    """Slow per-item progress transitions in dev when enabled."""
    await maybe_debug_sleep(settings, settings.import_debug_item_delay_seconds)


async def load_import_media_settings(session: AsyncSession) -> dict[str, str]:
    """Load media-management settings honored by import execution."""
    ingest_policy = await load_library_ingest_policy(session)
    return import_media_settings_from_policy(
        ingest_policy,
        utility_trash_folder=await load_import_utility_trash_folder(session),
    )


async def load_cached_import_media_settings(
    session: AsyncSession,
    job: Any,
    cache: ImportRuntimeCache,
) -> dict[str, str]:
    """Load and memoize media-management settings for one active import job."""
    if cache.media_settings is None:
        ingest_policy = await load_cached_import_ingest_policy(session, job, cache)
        cache.media_settings = import_media_settings_from_policy(
            ingest_policy,
            utility_trash_folder=await load_import_utility_trash_folder(session),
        )
    return cache.media_settings


async def load_cached_import_ingest_policy(
    session: AsyncSession,
    job: Any,
    cache: ImportRuntimeCache,
) -> LibraryIngestPolicy:
    """Load and memoize the effective ingest policy for one active import job."""
    if cache.ingest_policy is None:
        snapshot_policy = library_ingest_policy_from_snapshot(
            getattr(job, "ingest_policy_snapshot", None) or {}
        )
        cache.ingest_policy = snapshot_policy or await load_library_ingest_policy(session)
    return cache.ingest_policy


async def load_cached_import_permission_policy(
    session: AsyncSession,
    cache: ImportRuntimeCache,
) -> LibraryPermissionPolicy:
    """Load and memoize the effective permission policy for one active import job."""
    if cache.permission_policy is None:
        cache.permission_policy = await load_library_permission_policy(session)
    return cache.permission_policy


async def load_import_utility_trash_folder(session: AsyncSession) -> str:
    """Load the utility trash folder setting used by import rollback staging."""
    result = await session.execute(
        sa_select(SystemConfig.value).where(SystemConfig.key == "utility_trash_folder")
    )
    return str(result.scalar_one_or_none() or "")


def import_media_settings_from_policy(
    ingest_policy: LibraryIngestPolicy,
    *,
    utility_trash_folder: str = "",
) -> dict[str, str]:
    """Build import media settings from a frozen ingest policy snapshot."""
    return {
        "post_processing_method": ingest_policy.post_processing_method,
        "torrent_import_strategy": ingest_policy.torrent_import_strategy,
        "convert_to_preferred_format_on_import": (
            "true" if ingest_policy.normalize_imported_archives_to_cbz else "false"
        ),
        "skip_existing_files": "true" if ingest_policy.skip_existing_files else "false",
        "update_embedded_comicinfo_from_match_on_import": (
            "true" if ingest_policy.update_embedded_comicinfo_from_match else "false"
        ),
        "utility_trash_folder": utility_trash_folder,
    }


async def resolve_import_file_extensions(
    session: AsyncSession,
    configured_formats: str | None,
) -> frozenset[str]:
    """Resolve import file extensions from the job override or global safety config."""
    if configured_formats:
        return frozenset(
            f".{ext.strip().lower().lstrip('.')}"
            for ext in configured_formats.split(",")
            if ext.strip()
        )
    return frozenset(await get_allowed_extensions(session))


async def load_utility_trash_dir(
    session: AsyncSession,
    settings: PullboxSettings,
    *,
    load_media_settings: Callable[[AsyncSession], Awaitable[dict[str, str]]],
) -> Path:
    """Resolve the effective utility trash directory for import rollback safety."""
    media_settings = await load_media_settings(session)
    return resolve_utility_directory(
        db_value=media_settings["utility_trash_folder"],
        default_parent=settings.library_root,
        default_subdir=".trash",
        library_root=settings.library_root,
        data_dir=settings.data_dir,
    )


async def load_cached_utility_trash_dir(
    session: AsyncSession,
    settings: PullboxSettings,
    job: Any,
    cache: ImportRuntimeCache,
) -> Path:
    """Resolve and memoize the effective utility trash directory for one import job."""
    if cache.trash_dir is None:
        cache.trash_dir = await load_utility_trash_dir(
            session,
            settings,
            load_media_settings=lambda run_session: load_cached_import_media_settings(
                run_session,
                job,
                cache,
            ),
        )
    return cache.trash_dir
