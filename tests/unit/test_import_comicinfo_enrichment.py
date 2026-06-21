from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.services.import_comicinfo_enrichment import (
    run_import_comicinfo_enrichment,
    run_pending_import_comicinfo_enrichment,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_run_import_comicinfo_enrichment_rewrites_pending_library_file(
    async_engine,
    tmp_path: Path,
) -> None:
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    archive_path = tmp_path / "King Dracula 004.cbz"
    archive_path.write_text("archive")

    async with session_factory() as session:
        root = LibraryRoot(name="Comics", path=str(tmp_path), enabled=True)
        series = Series(
            title="King Dracula",
            sort_title="king dracula",
            year_start=2024,
            comicvine_id=171911,
            issue_count=4,
        )
        session.add_all([root, series])
        await session.flush()
        issue = Issue(
            series_id=series.id,
            issue_number=4.0,
            comicvine_id=1234567,
            issue_type=IssueType.ISSUE,
            status=IssueStatus.WANTED,
        )
        session.add(issue)
        await session.flush()
        library_file = LibraryFile(
            file_path=str(archive_path),
            file_name=archive_path.name,
            file_size=archive_path.stat().st_size,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(tz=UTC),
            match_confidence=MatchConfidence.HIGH,
            issue_id=issue.id,
            library_root_id=root.id,
        )
        job = ImportJob(
            source_path=str(tmp_path),
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.COMPLETED,
        )
        imported_series = ImportedSeries(
            import_job_id=1,
            raw_series_name="King Dracula",
            status=ImportSeriesStatus.IMPORTED,
            series_id=series.id,
        )
        session.add_all([library_file, job])
        await session.flush()
        imported_series.import_job_id = job.id
        session.add(imported_series)
        await session.flush()
        imported_file = ImportedFile(
            import_job_id=job.id,
            import_series_id=imported_series.id,
            file_path=str(tmp_path / "source.cbz"),
            file_name="source.cbz",
            file_size=100,
            file_format="cbz",
            parsed_series="King Dracula",
            parsed_issue_number=4.0,
            status=ImportedFileStatus.IMPORTED,
            matched_issue_id=issue.id,
            library_file_id=library_file.id,
            diagnostics={
                "comicinfo_enrichment": {
                    "status": "pending",
                    "reason": "deferred_during_import",
                    "issue_id": issue.id,
                    "issue_cv_id": issue.comicvine_id,
                    "library_file_id": library_file.id,
                }
            },
        )
        session.add(imported_file)
        await session.commit()
        job_id = job.id
        issue_id = issue.id
        imported_file_id = imported_file.id

    async def build_payload(
        session: AsyncSession,
        issue: Issue,
        *,
        source_path: Path | None = None,
        defer_issue_enrichment: bool = False,
    ) -> dict[str, Any]:
        assert source_path == archive_path
        assert defer_issue_enrichment is False
        issue.description = "Refreshed ComicVine summary."
        issue.release_date = date(2026, 6, 17)
        issue.comicvine_url = "https://comicvine.gamespot.com/king-dracula-4/4000-1234567/"
        return {
            "Series": "King Dracula",
            "Number": "4",
            "Summary": issue.description,
            "Year": issue.release_date.year,
        }

    applied: list[tuple[Path, dict[str, Any]]] = []

    def apply_comicinfo(artifact_path: Path, payload: dict[str, Any]) -> None:
        applied.append((artifact_path, dict(payload)))
        artifact_path.write_text("updated archive")

    log_events: list[str] = []

    async def log_event(
        session: AsyncSession,
        job_id: int,
        level: str,
        event: str,
        *,
        message: str,
        **details: Any,
    ) -> None:
        _ = session, job_id, level, message, details
        log_events.append(event)

    await run_import_comicinfo_enrichment(
        session_factory,
        job_id=job_id,
        build_comicinfo_payload=build_payload,
        apply_comicinfo=apply_comicinfo,
        log_event=log_event,
    )

    assert applied == [
        (
            archive_path,
            {
                "Series": "King Dracula",
                "Number": "4",
                "Summary": "Refreshed ComicVine summary.",
                "Year": 2026,
            },
        )
    ]
    assert "import_file_comicinfo_enrichment_completed" in log_events
    async with session_factory() as session:
        imported_file = await session.get(ImportedFile, imported_file_id)
        issue = await session.get(Issue, issue_id)
        assert imported_file is not None
        assert issue is not None
        assert imported_file.diagnostics["comicinfo_enrichment"]["status"] == "complete"
        assert imported_file.diagnostics["comicinfo_enrichment"]["library_file_id"] is not None
        assert issue.description == "Refreshed ComicVine summary."


@pytest.mark.asyncio
async def test_run_pending_import_comicinfo_enrichment_recovers_completed_jobs_after_restart(
    async_engine,
    tmp_path: Path,
) -> None:
    """Startup recovery should resume deferred ComicInfo work lost during restart."""
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    archive_path = tmp_path / "Recovered Issue.cbz"
    archive_path.write_text("archive")

    async with session_factory() as session:
        root = LibraryRoot(name="Comics", path=str(tmp_path), enabled=True)
        series = Series(
            title="Recovered Series",
            sort_title="recovered series",
            year_start=2026,
            comicvine_id=999001,
            issue_count=1,
        )
        session.add_all([root, series])
        await session.flush()
        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            comicvine_id=999101,
            issue_type=IssueType.ISSUE,
            status=IssueStatus.WANTED,
        )
        session.add(issue)
        await session.flush()
        library_file = LibraryFile(
            file_path=str(archive_path),
            file_name=archive_path.name,
            file_size=archive_path.stat().st_size,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(tz=UTC),
            match_confidence=MatchConfidence.HIGH,
            issue_id=issue.id,
            library_root_id=root.id,
        )
        completed_job = ImportJob(
            source_path=str(tmp_path),
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.COMPLETED,
        )
        running_job = ImportJob(
            source_path=str(tmp_path),
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.IMPORTING,
        )
        session.add_all([library_file, completed_job, running_job])
        await session.flush()
        completed_series = ImportedSeries(
            import_job_id=completed_job.id,
            raw_series_name="Recovered Series",
            status=ImportSeriesStatus.IMPORTED,
            series_id=series.id,
        )
        running_series = ImportedSeries(
            import_job_id=running_job.id,
            raw_series_name="Running Series",
            status=ImportSeriesStatus.IMPORTING,
            series_id=series.id,
        )
        session.add_all([completed_series, running_series])
        await session.flush()
        session.add_all(
            [
                ImportedFile(
                    import_job_id=completed_job.id,
                    import_series_id=completed_series.id,
                    file_path=str(tmp_path / "source.cbz"),
                    file_name="source.cbz",
                    file_size=100,
                    file_format="cbz",
                    parsed_series="Recovered Series",
                    parsed_issue_number=1.0,
                    status=ImportedFileStatus.IMPORTED,
                    matched_issue_id=issue.id,
                    library_file_id=library_file.id,
                    diagnostics={
                        "comicinfo_enrichment": {
                            "status": "pending",
                            "reason": "deferred_during_import",
                            "issue_id": issue.id,
                            "issue_cv_id": issue.comicvine_id,
                            "library_file_id": library_file.id,
                        }
                    },
                ),
                ImportedFile(
                    import_job_id=running_job.id,
                    import_series_id=running_series.id,
                    file_path=str(tmp_path / "running.cbz"),
                    file_name="running.cbz",
                    file_size=100,
                    file_format="cbz",
                    parsed_series="Running Series",
                    parsed_issue_number=1.0,
                    status=ImportedFileStatus.IMPORTED,
                    matched_issue_id=issue.id,
                    library_file_id=library_file.id,
                    diagnostics={
                        "comicinfo_enrichment": {
                            "status": "pending",
                            "reason": "deferred_during_import",
                            "issue_id": issue.id,
                            "issue_cv_id": issue.comicvine_id,
                            "library_file_id": library_file.id,
                        }
                    },
                ),
            ]
        )
        await session.commit()

    applied: list[Path] = []

    async def build_payload(
        session: AsyncSession,
        issue: Issue,
        *,
        source_path: Path | None = None,
        defer_issue_enrichment: bool = False,
    ) -> dict[str, Any]:
        _ = session, issue, source_path
        assert defer_issue_enrichment is False
        return {"Series": "Recovered Series", "Number": "1"}

    def apply_comicinfo(artifact_path: Path, payload: dict[str, Any]) -> None:
        _ = payload
        applied.append(artifact_path)
        artifact_path.write_text("recovered archive")

    log_events: list[str] = []

    async def log_event(
        session: AsyncSession,
        job_id: int,
        level: str,
        event: str,
        *,
        message: str,
        **details: Any,
    ) -> None:
        _ = session, job_id, level, message, details
        log_events.append(event)

    recovered_jobs = await run_pending_import_comicinfo_enrichment(
        session_factory,
        build_comicinfo_payload=build_payload,
        apply_comicinfo=apply_comicinfo,
        log_event=log_event,
    )

    assert recovered_jobs == 1
    assert applied == [archive_path]
    assert archive_path.read_text() == "recovered archive"
    assert log_events == ["import_file_comicinfo_enrichment_completed"]
