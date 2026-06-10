"""Tests for import runtime and settings helper shims."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from pullbox.config import PullboxSettings
from pullbox.core.library_policy import LibraryIngestPolicy, serialize_library_ingest_policy
from pullbox.models.config import SystemConfig
from pullbox.services.import_service import ImportService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _make_service() -> ImportService:
    return ImportService(
        series_service=AsyncMock(),
        metadata_service=AsyncMock(),
        event_bus=AsyncMock(),
    )


async def test_load_import_media_settings_returns_effective_ingest_policy(
    db_session: AsyncSession,
) -> None:
    service = _make_service()
    db_session.add_all(
        [
            SystemConfig(key="post_processing_method", value="copy", value_type="string"),
            SystemConfig(
                key="torrent_import_strategy",
                value="seed_safe",
                value_type="string",
            ),
            SystemConfig(
                key="convert_to_preferred_format_on_import",
                value="true",
                value_type="bool",
            ),
            SystemConfig(key="skip_existing_files", value="true", value_type="bool"),
            SystemConfig(
                key="update_embedded_comicinfo_from_match_on_import",
                value="true",
                value_type="bool",
            ),
            SystemConfig(
                key="utility_trash_folder",
                value="{data}/import-trash",
                value_type="string",
            ),
        ]
    )
    await db_session.flush()

    settings = await service._load_import_media_settings(
        db_session,
        SimpleNamespace(id=1, ingest_policy_snapshot={}),
    )

    assert settings == {
        "post_processing_method": "copy",
        "torrent_import_strategy": "seed_safe",
        "convert_to_preferred_format_on_import": "true",
        "skip_existing_files": "true",
        "update_embedded_comicinfo_from_match_on_import": "true",
        "utility_trash_folder": "{data}/import-trash",
    }


async def test_cached_ingest_policy_reuses_job_snapshot(
    db_session: AsyncSession,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.services import import_runtime_settings
    from pullbox.services.import_runtime_settings import (
        ImportRuntimeCache,
        load_cached_import_ingest_policy,
    )

    snapshot_policy = LibraryIngestPolicy(
        rename_on_import=True,
        series_folder_template="{Series} ({Year})",
        comic_file_template="{Series} #{Issue}",
        annual_file_template="{Series} Annual #{Issue}",
        non_standard_file_template="{Series} {IssueType}",
        single_non_standard_file_template="{Series}",
        replace_illegal_characters=True,
        colon_replacement=" - ",
        post_processing_method="move",
        torrent_import_strategy="copy",
        normalize_imported_archives_to_cbz=True,
        skip_existing_files=True,
        update_embedded_comicinfo_from_match=True,
    )
    job = SimpleNamespace(
        id=99,
        ingest_policy_snapshot=serialize_library_ingest_policy(snapshot_policy),
    )
    cache = ImportRuntimeCache()
    live_loader = AsyncMock(side_effect=AssertionError("live config should not load"))
    monkeypatch.setattr(import_runtime_settings, "load_library_ingest_policy", live_loader)

    loaded = await load_cached_import_ingest_policy(db_session, job, cache)
    loaded_again = await load_cached_import_ingest_policy(db_session, job, cache)

    assert loaded == snapshot_policy
    assert loaded_again is loaded
    live_loader.assert_not_awaited()


async def test_resolve_import_file_extensions_prefers_job_override(
    db_session: AsyncSession,
) -> None:
    service = _make_service()
    db_session.add(
        SystemConfig(
            key="allowed_import_extensions",
            value=".cbz,.pdf",
            value_type="string",
        )
    )
    await db_session.flush()

    extensions = await service._resolve_import_file_extensions(db_session, " cbz, cbr ,PDF ")

    assert extensions == frozenset({".cbz", ".cbr", ".pdf"})


async def test_resolve_import_file_extensions_uses_file_safety_allowlist(
    db_session: AsyncSession,
) -> None:
    service = _make_service()
    db_session.add(
        SystemConfig(
            key="allowed_import_extensions",
            value="cbz,pdf",
            value_type="string",
        )
    )
    await db_session.flush()

    extensions = await service._resolve_import_file_extensions(db_session, None)

    assert extensions == frozenset({".cbz", ".pdf"})


async def test_load_utility_trash_dir_expands_runtime_placeholders(
    db_session: AsyncSession,
) -> None:
    service = _make_service()
    service._settings = PullboxSettings(
        data_dir="/tmp/pullbox-data",
        library_root="/tmp/pullbox-library",
    )
    db_session.add(
        SystemConfig(
            key="utility_trash_folder",
            value="{data}/import-trash",
            value_type="string",
        )
    )
    await db_session.flush()

    trash_dir = await service._load_utility_trash_dir(
        db_session,
        SimpleNamespace(id=1, ingest_policy_snapshot={}),
    )

    assert trash_dir.as_posix() == "/tmp/pullbox-data/import-trash"


async def test_maybe_debug_sleep_only_sleeps_when_slow_mode_enabled(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    service = _make_service()
    service._settings = PullboxSettings(import_debug_slow_mode=False)

    await service._maybe_debug_sleep(0.25)

    sleep.assert_not_awaited()

    service._settings = PullboxSettings(import_debug_slow_mode=True)
    await service._maybe_debug_sleep(0.25)

    sleep.assert_awaited_once_with(0.25)
