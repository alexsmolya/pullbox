"""Unit tests for background catalog hydration helpers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.models.series import IssueCatalogState, Series
from pullbox.services.import_catalog_hydration import mark_catalog_hydration_failed


async def test_mark_catalog_hydration_failed_sets_retryable_state(db_session) -> None:
    series = Series(
        title="Hydration Failure",
        sort_title="hydration failure",
        year_start=2026,
        comicvine_id=123456,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    db_session.add(series)
    await db_session.commit()

    session_factory = async_sessionmaker(
        db_session.bind,
        class_=type(db_session),
        expire_on_commit=False,
    )

    await mark_catalog_hydration_failed(
        session_factory,
        series_id=series.id,
        error="ComicVine timed out",
    )

    await db_session.refresh(series)
    assert series.issue_catalog_state == IssueCatalogState.FAILED
    assert series.issue_catalog_error == "ComicVine timed out"
    assert series.issue_catalog_last_synced_at is None
    assert series.issue_catalog_last_checked_at is None
