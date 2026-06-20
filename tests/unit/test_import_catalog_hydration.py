"""Unit tests for background catalog hydration helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.models.series import IssueCatalogState, Series
from pullbox.services.import_catalog_hydration import (
    mark_catalog_hydration_failed,
    run_pending_catalog_hydration,
)


class CatalogHydrationSeriesServiceStub:
    def __init__(self, *, failing_cv_ids: set[int] | None = None) -> None:
        self.failing_cv_ids = failing_cv_ids or set()
        self.prefetch_calls: list[int] = []
        self.add_calls: list[tuple[int, bool]] = []

    async def prefetch_comicvine_bundle(
        self,
        comicvine_id: int,
    ) -> tuple[dict[str, int], list[Any]]:
        self.prefetch_calls.append(comicvine_id)
        if comicvine_id in self.failing_cv_ids:
            raise RuntimeError(f"ComicVine failed for {comicvine_id}")
        return {"comicvine_id": comicvine_id}, []

    async def add_from_comicvine_prefetched(
        self,
        hydrate_session,
        *,
        comicvine_id: int,
        library_root_id: int | None,
        search_on_add: bool,
        series_meta,
        issue_summaries,
    ) -> Series:
        _ = library_root_id, series_meta, issue_summaries
        self.add_calls.append((comicvine_id, search_on_add))
        result = await hydrate_session.execute(
            sa_select(Series).where(Series.comicvine_id == comicvine_id)
        )
        series = result.scalar_one()
        series.issue_catalog_state = IssueCatalogState.COMPLETE
        series.issue_catalog_error = None
        await hydrate_session.flush()
        return series


async def test_run_pending_catalog_hydration_recovers_hydrating_series_after_restart(
    db_session,
) -> None:
    first = Series(
        title="First Restart Recovery",
        sort_title="first restart recovery",
        year_start=2026,
        comicvine_id=1001,
        monitored=True,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    already_complete = Series(
        title="Already Complete",
        sort_title="already complete",
        year_start=2026,
        comicvine_id=2001,
        issue_catalog_state=IssueCatalogState.COMPLETE,
    )
    second = Series(
        title="Second Restart Recovery",
        sort_title="second restart recovery",
        year_start=2026,
        comicvine_id=1002,
        monitored=False,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    no_provider_id = Series(
        title="No Provider ID",
        sort_title="no provider id",
        year_start=2026,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    db_session.add_all([first, already_complete, second, no_provider_id])
    await db_session.commit()

    session_factory = async_sessionmaker(
        db_session.bind,
        class_=type(db_session),
        expire_on_commit=False,
    )
    service = CatalogHydrationSeriesServiceStub()

    recovered = await run_pending_catalog_hydration(
        session_factory,
        series_service=service,
    )

    assert recovered == 2
    assert service.prefetch_calls == [1001, 1002]
    assert service.add_calls == [(1001, True), (1002, False)]
    for series in (first, second):
        await db_session.refresh(series)
        assert series.issue_catalog_state == IssueCatalogState.COMPLETE
        assert series.issue_catalog_error is None
    await db_session.refresh(already_complete)
    await db_session.refresh(no_provider_id)
    assert already_complete.issue_catalog_state == IssueCatalogState.COMPLETE
    assert no_provider_id.issue_catalog_state == IssueCatalogState.HYDRATING


async def test_run_pending_catalog_hydration_continues_after_series_failure(db_session) -> None:
    failed = Series(
        title="Failed Restart Recovery",
        sort_title="failed restart recovery",
        year_start=2026,
        comicvine_id=3001,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    recovered_series = Series(
        title="Recovered After Failure",
        sort_title="recovered after failure",
        year_start=2026,
        comicvine_id=3002,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    db_session.add_all([failed, recovered_series])
    await db_session.commit()

    session_factory = async_sessionmaker(
        db_session.bind,
        class_=type(db_session),
        expire_on_commit=False,
    )
    service = CatalogHydrationSeriesServiceStub(failing_cv_ids={3001})

    recovered = await run_pending_catalog_hydration(
        session_factory,
        series_service=service,
    )

    assert recovered == 1
    assert service.prefetch_calls == [3001, 3002]
    assert service.add_calls == [(3002, False)]
    await db_session.refresh(failed)
    await db_session.refresh(recovered_series)
    assert failed.issue_catalog_state == IssueCatalogState.FAILED
    assert failed.issue_catalog_error == "ComicVine failed for 3001"
    assert recovered_series.issue_catalog_state == IssueCatalogState.COMPLETE


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
