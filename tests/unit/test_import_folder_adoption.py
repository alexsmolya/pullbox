"""Tests for same-library-source import folder adoption."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select as sa_select

from pullbox.core.library_policy import LibraryIngestPolicy
from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportJobAction,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.models.library import LibraryRoot
from pullbox.models.series import Series
from pullbox.services.import_folder_adoption import (
    apply_import_series_folder_adoption,
    plan_import_series_folder_adoption,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def _ingest_policy(*, rename_on_import: bool = True) -> LibraryIngestPolicy:
    return LibraryIngestPolicy(
        rename_on_import=rename_on_import,
        series_folder_template="{Series} ({Year})",
        comic_file_template="{Series} ({Year}) #{Issue:03d}",
        annual_file_template="{Series} ({Year}) Annual #{Issue:03d}",
        non_standard_file_template="{Series} ({Year}) {Type}",
        single_non_standard_file_template="{Series} ({Year}) {Type}",
        replace_illegal_characters=True,
        colon_replacement="dash",
        post_processing_method="move",
        torrent_import_strategy="standard",
        normalize_imported_archives_to_cbz=False,
        skip_existing_files=False,
        update_embedded_comicinfo_from_match=False,
    )


async def _seed_import_row(
    session: AsyncSession,
    tmp_path: Path,
    *,
    source_folder_name: str = "Mylar Series",
    target_folder_name: str = "Canonical Series (2024)",
) -> tuple[ImportJob, ImportedSeries, ImportedFile, Series, Path, Path]:
    library_root_path = tmp_path / "comics"
    source_folder = library_root_path / source_folder_name
    target_folder = library_root_path / target_folder_name
    source_folder.mkdir(parents=True)
    (source_folder / "cover.jpg").write_text("sidecar", encoding="utf-8")
    source_file = source_folder / "Mylar Series 001.cbz"
    source_file.write_text("comic", encoding="utf-8")

    root = LibraryRoot(name="Comics", path=str(library_root_path), enabled=True)
    job = ImportJob(
        source_path=str(library_root_path),
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.IMPORTING,
        target_library_root_id=None,
        move_to_library=True,
        transfer_method="move",
    )
    series = Series(
        comicvine_id=12345,
        title="Canonical Series",
        sort_title="Canonical Series",
        year_start=2024,
        path=str(target_folder),
    )
    session.add_all([root, job, series])
    await session.flush()
    item = ImportedSeries(
        import_job_id=job.id,
        status=ImportSeriesStatus.CONFIRMED,
        raw_series_name="Mylar Series",
        file_count=1,
        files_total=1,
        source_folder=str(source_folder),
        series_id=series.id,
    )
    session.add(item)
    await session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=item.id,
        file_path=str(source_file),
        file_name=source_file.name,
        file_size=source_file.stat().st_size,
        file_format="cbz",
        status=ImportedFileStatus.MATCHED,
        include_in_import=True,
    )
    session.add(imp_file)
    await session.flush()
    return job, item, imp_file, series, source_folder, target_folder


async def test_plans_same_library_source_folder_adoption(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    job, item, imp_file, series, source_folder, target_folder = await _seed_import_row(
        db_session,
        tmp_path,
    )

    plan = await plan_import_series_folder_adoption(
        db_session,
        job,
        item,
        [imp_file],
        resolved_series_id=series.id,
        ingest_policy=_ingest_policy(),
    )

    assert plan is not None
    assert plan.source_folder == source_folder
    assert plan.target_folder == target_folder
    assert plan.series_id == series.id


async def test_does_not_adopt_when_source_folder_is_shared_by_multiple_series(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    job, item, imp_file, series, _source_folder, _target_folder = await _seed_import_row(
        db_session,
        tmp_path,
    )
    shared_item = ImportedSeries(
        import_job_id=job.id,
        status=ImportSeriesStatus.CONFIRMED,
        raw_series_name="Other Series",
        file_count=1,
        files_total=1,
        source_folder=item.source_folder,
        series_id=series.id,
    )
    db_session.add(shared_item)
    await db_session.flush()

    plan = await plan_import_series_folder_adoption(
        db_session,
        job,
        item,
        [imp_file],
        resolved_series_id=series.id,
        ingest_policy=_ingest_policy(),
    )

    assert plan is None


async def test_plans_adoption_when_target_folder_exists_but_is_empty(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    job, item, imp_file, series, _source_folder, target_folder = await _seed_import_row(
        db_session,
        tmp_path,
    )
    target_folder.mkdir(parents=True)

    plan = await plan_import_series_folder_adoption(
        db_session,
        job,
        item,
        [imp_file],
        resolved_series_id=series.id,
        ingest_policy=_ingest_policy(),
    )

    assert plan is not None
    assert plan.target_folder == target_folder


async def test_does_not_adopt_when_target_folder_has_existing_content(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    job, item, imp_file, series, _source_folder, target_folder = await _seed_import_row(
        db_session,
        tmp_path,
    )
    target_folder.mkdir(parents=True)
    (target_folder / "existing.cbz").write_text("already there", encoding="utf-8")

    plan = await plan_import_series_folder_adoption(
        db_session,
        job,
        item,
        [imp_file],
        resolved_series_id=series.id,
        ingest_policy=_ingest_policy(),
    )

    assert plan is None


async def test_apply_folder_adoption_renames_folder_preserves_sidecars_and_records_action(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    job, item, imp_file, series, source_folder, target_folder = await _seed_import_row(
        db_session,
        tmp_path,
    )
    recorded_actions: list[tuple[str, dict[str, Any]]] = []
    log_events: list[dict[str, Any]] = []

    async def record_action(
        session: AsyncSession,
        current_job: ImportJob,
        *,
        phase: str,
        action_type: str,
        payload: dict[str, Any],
    ) -> ImportJobAction:
        recorded_actions.append((action_type, payload))
        action = ImportJobAction(
            import_job_id=current_job.id,
            sequence_no=len(recorded_actions),
            phase=phase,
            action_type=action_type,
            status="COMPLETED",
            payload=payload,
        )
        session.add(action)
        await session.flush()
        return action

    async def log_event(*args: Any, **kwargs: Any) -> None:
        log_events.append(kwargs)

    imp_file_id = imp_file.id
    series_id = series.id
    job_id = job.id

    adopted = await apply_import_series_folder_adoption(
        db_session,
        job,
        item,
        [imp_file],
        resolved_series_id=series.id,
        ingest_policy=_ingest_policy(),
        record_action=record_action,
        log_event=log_event,
    )

    assert adopted is True
    assert not source_folder.exists()
    assert target_folder.exists()
    assert (target_folder / "cover.jpg").exists()
    assert imp_file.file_path == str(target_folder / "Mylar Series 001.cbz")
    assert series.path == str(target_folder)
    assert recorded_actions == [
        (
            "series_folder_renamed",
            {
                "series_id": series.id,
                "import_series_id": item.id,
                "old_folder_path": str(source_folder),
                "new_folder_path": str(target_folder),
                "old_series_path": str(target_folder),
                "old_library_root_id": None,
            },
        )
    ]
    assert log_events

    await db_session.rollback()
    persisted_file = await db_session.get(ImportedFile, imp_file_id)
    persisted_series = await db_session.get(Series, series_id)
    persisted_action = await db_session.scalar(
        sa_select(ImportJobAction).where(
            ImportJobAction.import_job_id == job_id,
            ImportJobAction.action_type == "series_folder_renamed",
        )
    )
    assert persisted_file is not None
    assert persisted_file.file_path == str(target_folder / "Mylar Series 001.cbz")
    assert persisted_series is not None
    assert persisted_series.path == str(target_folder)
    assert persisted_action is not None
