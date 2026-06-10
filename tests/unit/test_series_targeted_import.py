"""Unit tests for targeted-first series import metadata behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from pullbox.core.events import EventBus, SeriesAdded
from pullbox.models.import_job import ImportedSeries
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import IssueCatalogState, Series, SeriesStatus
from pullbox.providers.base import IssueSummary, SeriesMetadata
from pullbox.services.series_service import SeriesService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _fake_upsert_series(
    session: AsyncSession,
    cv_id: int,
    meta: SeriesMetadata,
) -> Series:
    existing = await session.scalar(select(Series).where(Series.comicvine_id == cv_id))
    if existing is not None:
        existing.title = meta.title
        existing.sort_title = meta.sort_title or meta.title
        existing.year_start = meta.year_start
        existing.issue_count = meta.issue_count or 0
        existing.comicvine_url = meta.comicvine_url
        await session.flush()
        return existing

    series = Series(
        comicvine_id=cv_id,
        title=meta.title,
        sort_title=meta.sort_title or meta.title,
        year_start=meta.year_start,
        status=SeriesStatus.CONTINUING,
        issue_count=meta.issue_count or 0,
        comicvine_url=meta.comicvine_url,
    )
    session.add(series)
    await session.flush()
    return series


async def _fake_upsert_issue_summaries(
    session: AsyncSession,
    series: Series,
    summaries: list[IssueSummary],
) -> list[Issue]:
    created: list[Issue] = []
    for summary in summaries:
        issue = Issue(
            series_id=series.id,
            comicvine_id=int(summary.provider_id),
            issue_number=summary.issue_number,
            title=summary.title,
            status=IssueStatus.SKIPPED,
        )
        session.add(issue)
        created.append(issue)
    await session.flush()
    return created


@pytest.mark.asyncio
async def test_targeted_import_creates_partial_catalog_without_emitting_series_added(
    db_session: AsyncSession,
) -> None:
    metadata = MagicMock()
    metadata.upsert_series_metadata = AsyncMock(side_effect=_fake_upsert_series)
    metadata.classify_and_link_series = AsyncMock()
    metadata.upsert_issue_summaries = AsyncMock(side_effect=_fake_upsert_issue_summaries)
    metadata.infer_series_status = AsyncMock()
    event_bus = EventBus()
    emitted: list[SeriesAdded] = []
    event_bus.subscribe(SeriesAdded, emitted.append)
    service = SeriesService(metadata_service=metadata, event_bus=event_bus)
    import_series = ImportedSeries(
        raw_series_name="King Dracula",
        cv_id=166904,
        cv_title="King Dracula",
        cv_year=2025,
        cv_publisher="Dynamite",
        cv_issue_count=3,
        cv_url="https://comicvine.gamespot.com/king-dracula/4050-166904/",
    )

    series = await service.add_from_import_review_targeted(
        db_session,
        import_series=import_series,
        library_root_id=None,
        search_on_add=True,
        issue_summaries=[
            IssueSummary(
                provider_id="120004",
                issue_number=4.0,
                title="Issue 4",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
        ],
    )

    assert series.monitored is True
    assert series.issue_catalog_state == IssueCatalogState.HYDRATING
    assert series.issue_catalog_error is None
    assert emitted == []
    issues = (await db_session.scalars(select(Issue).where(Issue.series_id == series.id))).all()
    assert [(issue.issue_number, issue.comicvine_id) for issue in issues] == [(4.0, 120004)]


@pytest.mark.asyncio
async def test_hydrate_series_catalog_marks_complete_and_emits_series_added(
    db_session: AsyncSession,
) -> None:
    metadata = MagicMock()
    metadata.upsert_series_metadata = AsyncMock(side_effect=_fake_upsert_series)
    metadata.classify_and_link_series = AsyncMock()
    metadata.upsert_issue_summaries = AsyncMock(side_effect=_fake_upsert_issue_summaries)
    metadata.infer_series_status = AsyncMock()
    event_bus = EventBus()
    emitted: list[SeriesAdded] = []
    event_bus.subscribe(SeriesAdded, emitted.append)
    service = SeriesService(metadata_service=metadata, event_bus=event_bus)
    series = Series(
        comicvine_id=166904,
        title="King Dracula",
        sort_title="king dracula",
        monitored=True,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    db_session.add(series)
    await db_session.flush()
    metadata.get_series_metadata = AsyncMock(
        return_value=SeriesMetadata(
            provider_id="166904",
            title="King Dracula",
            sort_title="King Dracula",
            year_start=2025,
            year_end=None,
            status="continuing",
            publisher="Dynamite",
            description=None,
            cover_url=None,
            issue_count=4,
            comicvine_url="https://comicvine.gamespot.com/king-dracula/4050-166904/",
        )
    )
    metadata.get_issue_summaries_for_series = AsyncMock(
        return_value=[
            IssueSummary(
                provider_id="120001",
                issue_number=1.0,
                title="Issue 1",
                release_date=None,
                cover_url=None,
                issue_type="issue",
            )
        ]
    )

    await service.hydrate_series_catalog(db_session, series.id, search_on_add=True)
    await db_session.refresh(series)

    assert series.issue_catalog_state == IssueCatalogState.COMPLETE
    assert series.issue_catalog_last_synced_at is not None
    assert series.issue_catalog_error is None
    assert emitted == [SeriesAdded(series_id=series.id, comicvine_id=166904)]
