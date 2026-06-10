"""Tests for import file-matching target lookup helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from pullbox.core.exceptions import ImportProviderDegradedError
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
from pullbox.models.series import Series, SeriesType
from pullbox.providers.base import IssueSummary
from pullbox.services.import_file_match_targets import load_file_match_target_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _IssueSummaryProvider:
    def __init__(self, summaries: list[IssueSummary]) -> None:
        self.summaries = summaries
        self.requested_series_id: str | None = None

    async def get_issues_for_series(self, series_provider_id: str) -> list[IssueSummary]:
        self.requested_series_id = series_provider_id
        return self.summaries


class _TargetedIssueSummaryProvider(_IssueSummaryProvider):
    def __init__(self, summaries: list[IssueSummary]) -> None:
        super().__init__(summaries)
        self.requested_issue_numbers: list[float] | None = None
        self.full_fetch_called = False

    async def get_issues_for_series(self, series_provider_id: str) -> list[IssueSummary]:
        self.full_fetch_called = True
        return await super().get_issues_for_series(series_provider_id)

    async def get_issues_for_series_by_numbers(
        self,
        series_provider_id: str,
        issue_numbers: list[float],
    ) -> list[IssueSummary]:
        self.requested_series_id = series_provider_id
        self.requested_issue_numbers = issue_numbers
        requested = set(issue_numbers)
        return [summary for summary in self.summaries if summary.issue_number in requested]


async def _create_job(session: AsyncSession) -> ImportJob:
    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.FILE_MATCHING,
    )
    session.add(job)
    await session.flush()
    return job


async def test_load_file_match_target_index_uses_existing_series_issues(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    series = Series(
        title="Absolute Wonder Woman",
        sort_title="absolute wonder woman",
        year_start=2024,
        comicvine_id=165732,
        series_type=SeriesType.STANDARD,
    )
    db_session.add(series)
    await db_session.flush()
    wanted_issue = Issue(
        series_id=series.id,
        issue_number=19.0,
        comicvine_id=100019,
        title="Issue 19",
        status=IssueStatus.WANTED,
    )
    owned_issue = Issue(
        series_id=series.id,
        issue_number=20.0,
        comicvine_id=100020,
        title="Issue 20",
        status=IssueStatus.OWNED,
    )
    db_session.add_all([wanted_issue, owned_issue])
    await db_session.flush()
    root = LibraryRoot(name="Main", path="/library/main")
    db_session.add(root)
    await db_session.flush()
    db_session.add(
        LibraryFile(
            file_path="/library/main/Absolute Wonder Woman 020.cbz",
            file_name="Absolute Wonder Woman 020.cbz",
            file_size=2048,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(UTC),
            match_confidence=MatchConfidence.HIGH,
            issue_id=owned_issue.id,
            library_root_id=root.id,
        )
    )
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Absolute Wonder Woman",
        status=ImportSeriesStatus.DUPLICATE,
        series_id=series.id,
    )
    db_session.add(imported_series)
    await db_session.flush()

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=True,
        metadata_provider=None,
    )

    assert target_index.has_targets is True
    assert target_index.existing_series == series
    assert target_index.issue_entries == [(wanted_issue, False), (owned_issue, True)]
    assert target_index.cv_id_map[100019] == (
        wanted_issue.id,
        100019,
        False,
        wanted_issue,
        "Issue 19",
    )
    assert target_index.cv_id_map[100020] == (
        owned_issue.id,
        100020,
        True,
        owned_issue,
        "Issue 20",
    )
    assert target_index.number_map[19.0] == (
        wanted_issue.id,
        100019,
        False,
        wanted_issue,
        "Issue 19",
    )
    assert target_index.number_map[20.0] == (
        owned_issue.id,
        100020,
        True,
        owned_issue,
        "Issue 20",
    )


async def test_load_file_match_target_index_uses_provider_summaries_for_new_series(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Absolute Batman",
        status=ImportSeriesStatus.MATCHED,
        cv_id=165733,
    )
    db_session.add(imported_series)
    await db_session.flush()
    provider = _IssueSummaryProvider(
        [
            IssueSummary(
                provider_id="200001",
                issue_number=1.0,
                title="Issue 1",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            ),
            IssueSummary(
                provider_id="",
                issue_number=2.0,
                title="Issue 2",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            ),
        ]
    )

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
    )

    assert provider.requested_series_id == "165733"
    assert target_index.existing_series is None
    assert target_index.issue_entries == []
    assert target_index.cv_id_map == {200001: (None, 200001, False, None, "Issue 1")}
    assert target_index.number_map == {
        1.0: (None, 200001, False, None, "Issue 1"),
        2.0: (None, None, False, None, "Issue 2"),
    }


async def test_load_file_match_target_index_fetches_only_requested_issue_numbers(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="2000 AD",
        status=ImportSeriesStatus.MATCHED,
        cv_id=19752,
        cv_issue_count=2484,
    )
    db_session.add(imported_series)
    await db_session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=imported_series.id,
        file_path="/tmp/2000AD prog 2483.cbz",
        file_name="2000AD prog 2483.cbz",
        file_size=1024,
        file_format="cbz",
        parsed_series="2000AD",
        parsed_issue_number=2483.0,
        status=ImportedFileStatus.PENDING,
    )
    provider = _TargetedIssueSummaryProvider(
        [
            IssueSummary(
                provider_id="1248300",
                issue_number=2483.0,
                title="Prog 2483",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
        ]
    )

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=[imp_file],
    )

    assert provider.requested_series_id == "19752"
    assert provider.requested_issue_numbers == [2483.0]
    assert provider.full_fetch_called is False
    assert target_index.number_map == {2483.0: (None, 1248300, False, None, "Prog 2483")}


async def test_load_file_match_target_index_full_fetches_single_issue_volume_subtitle(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Marvel Action: Spider-Man: Spider-Chase",
        status=ImportSeriesStatus.MATCHED,
        cv_id=122410,
        cv_issue_count=1,
    )
    db_session.add(imported_series)
    await db_session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=imported_series.id,
        file_path="/tmp/Marvel Action Spider-Man v02 - Spider-Chase.cbr",
        file_name="Marvel Action Spider-Man v02 - Spider-Chase (2019) (Digital).cbr",
        file_size=1024,
        file_format="cbr",
        parsed_series="Marvel Action Spider-Man",
        parsed_issue_number=2.0,
        status=ImportedFileStatus.PENDING,
        diagnostics={"source_issue_type": IssueType.VOLUME.value},
    )
    provider = _TargetedIssueSummaryProvider(
        [
            IssueSummary(
                provider_id="711738",
                issue_number=1.0,
                title="Spider-Chase",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
        ]
    )

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=[imp_file],
    )

    assert provider.requested_series_id == "122410"
    assert provider.requested_issue_numbers is None
    assert provider.full_fetch_called is True
    assert target_index.number_map == {1.0: (None, 711738, False, None, "Spider-Chase")}


async def test_load_file_match_target_index_full_fetches_single_issue_embedded_number_title(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="He-Man and the Masters of the Universe - Episode - Captured",
        status=ImportSeriesStatus.MATCHED,
        cv_id=158984,
        cv_title="He-Man and the Masters of the Universe: Episode 40 - Captured",
        cv_issue_count=1,
    )
    db_session.add(imported_series)
    await db_session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=imported_series.id,
        file_path="/tmp/He-Man and the Masters of the Universe - Episode 40 - Captured.cbr",
        file_name=(
            "He-Man and the Masters of the Universe - Episode 40 - Captured (2008) (digital).cbr"
        ),
        file_size=1024,
        file_format="cbr",
        parsed_series="He-Man and the Masters of the Universe - Episode - Captured",
        parsed_issue_number=40.0,
        status=ImportedFileStatus.PENDING,
        diagnostics={"source_issue_type": IssueType.ISSUE.value},
    )
    provider = _TargetedIssueSummaryProvider(
        [
            IssueSummary(
                provider_id="730001",
                issue_number=1.0,
                title="Issue 1",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
        ]
    )

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=[imp_file],
    )

    assert provider.requested_series_id == "158984"
    assert provider.requested_issue_numbers is None
    assert provider.full_fetch_called is True
    assert target_index.number_map == {1.0: (None, 730001, False, None, "Issue 1")}


async def test_load_file_match_target_index_does_not_full_fetch_plain_issue_number(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Batman",
        status=ImportSeriesStatus.MATCHED,
        cv_id=190040,
        cv_title="Batman 40 - Anniversary",
        cv_issue_count=1,
    )
    db_session.add(imported_series)
    await db_session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=imported_series.id,
        file_path="/tmp/Batman 040.cbz",
        file_name="Batman 040 (2026) (Digital).cbz",
        file_size=1024,
        file_format="cbz",
        parsed_series="Batman",
        parsed_issue_number=40.0,
        status=ImportedFileStatus.PENDING,
    )
    provider = _TargetedIssueSummaryProvider([])

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=[imp_file],
    )

    assert provider.requested_series_id == "190040"
    assert provider.requested_issue_numbers == [40.0]
    assert provider.full_fetch_called is False
    assert target_index.has_targets is False


async def test_load_file_match_target_index_full_fetches_small_multi_issue_series(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Small Run",
        status=ImportSeriesStatus.MATCHED,
        cv_id=12345,
        cv_issue_count=4,
    )
    db_session.add(imported_series)
    await db_session.flush()
    files = [
        ImportedFile(
            import_job_id=job.id,
            import_series_id=imported_series.id,
            file_path=f"/tmp/Small Run {issue_number:03d}.cbz",
            file_name=f"Small Run {issue_number:03d}.cbz",
            file_size=1024,
            file_format="cbz",
            parsed_series="Small Run",
            parsed_issue_number=float(issue_number),
            status=ImportedFileStatus.PENDING,
        )
        for issue_number in (1, 2, 3)
    ]
    provider = _TargetedIssueSummaryProvider(
        [
            IssueSummary(
                provider_id=str(120000 + issue_number),
                issue_number=float(issue_number),
                title=f"Issue {issue_number}",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
            for issue_number in (1, 2, 3, 4)
        ]
    )

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=files,
    )

    assert provider.requested_series_id == "12345"
    assert provider.requested_issue_numbers is None
    assert provider.full_fetch_called is True
    assert sorted(target_index.number_map) == [1.0, 2.0, 3.0, 4.0]


async def test_load_file_match_target_index_skips_huge_full_fetch_without_file_identity(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="2000 AD",
        status=ImportSeriesStatus.MATCHED,
        cv_id=19752,
        cv_issue_count=2484,
    )
    db_session.add(imported_series)
    await db_session.flush()
    imp_file = ImportedFile(
        import_job_id=job.id,
        import_series_id=imported_series.id,
        file_path="/tmp/2000AD unknown.cbz",
        file_name="2000AD unknown.cbz",
        file_size=1024,
        file_format="cbz",
        parsed_series="2000AD",
        parsed_issue_number=None,
        status=ImportedFileStatus.PENDING,
    )
    provider = _TargetedIssueSummaryProvider([])

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=provider,
        files=[imp_file],
    )

    assert provider.full_fetch_called is False
    assert target_index.has_targets is False


async def test_load_file_match_target_index_without_target_identity_returns_empty(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="No Target Series",
        status=ImportSeriesStatus.MATCHED,
    )
    db_session.add(imported_series)
    await db_session.flush()

    target_index = await load_file_match_target_index(
        db_session,
        imported_series,
        duplicate_series=False,
        metadata_provider=None,
    )

    assert target_index.has_targets is False
    assert target_index.existing_series is None
    assert target_index.issue_entries == []
    assert target_index.cv_id_map == {}
    assert target_index.number_map == {}


async def test_load_file_match_target_index_raises_when_provider_returns_no_issue_targets(
    db_session: AsyncSession,
) -> None:
    job = await _create_job(db_session)
    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="The Banks",
        raw_year=2019,
        status=ImportSeriesStatus.MATCHED,
        cv_id=122775,
    )
    db_session.add(imported_series)
    await db_session.flush()
    provider = _IssueSummaryProvider([])

    with pytest.raises(ImportProviderDegradedError, match="The Banks"):
        await load_file_match_target_index(
            db_session,
            imported_series,
            duplicate_series=False,
            metadata_provider=provider,
        )
