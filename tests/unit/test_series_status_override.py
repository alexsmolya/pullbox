"""Series lifecycle override behavior."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import (
    Series,
    SeriesStatus,
    SeriesStatusOverride,
    SeriesType,
)
from pullbox.services.series_service import SeriesService


def _service(metadata: SimpleNamespace) -> SeriesService:
    return SeriesService(metadata_service=metadata, event_bus=MagicMock())


@pytest.mark.asyncio
async def test_mark_series_ended_sets_override_and_derived_end_year(db_session) -> None:  # type: ignore[no-untyped-def]
    metadata = SimpleNamespace(
        derive_series_end_year=AsyncMock(return_value=2026),
        refresh_series=AsyncMock(),
        infer_series_status=AsyncMock(),
    )
    service = _service(metadata)
    series = Series(
        title="Active Series",
        sort_title="Active Series",
        year_start=2024,
        status=SeriesStatus.CONTINUING,
        series_type=SeriesType.STANDARD,
    )
    db_session.add(series)
    await db_session.flush()
    db_session.add(
        Issue(
            series_id=series.id,
            issue_number=1,
            release_date=date(2026, 1, 1),
            status=IssueStatus.OWNED,
        )
    )
    await db_session.flush()

    updated = await service.set_status_override(
        db_session,
        series.id,
        SeriesStatusOverride.ENDED,
    )

    assert updated.status == SeriesStatus.ENDED
    assert updated.status_override == SeriesStatusOverride.ENDED
    assert updated.year_end == 2026
    metadata.derive_series_end_year.assert_awaited_once_with(db_session, series)
    metadata.refresh_series.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_series_continuing_clears_end_year(db_session) -> None:  # type: ignore[no-untyped-def]
    metadata = SimpleNamespace(
        derive_series_end_year=AsyncMock(),
        refresh_series=AsyncMock(),
        infer_series_status=AsyncMock(),
    )
    service = _service(metadata)
    series = Series(
        title="Ended Series",
        sort_title="Ended Series",
        year_start=2020,
        year_end=2024,
        status=SeriesStatus.ENDED,
        series_type=SeriesType.STANDARD,
    )
    db_session.add(series)
    await db_session.flush()

    updated = await service.set_status_override(
        db_session,
        series.id,
        SeriesStatusOverride.CONTINUING,
    )

    assert updated.status == SeriesStatus.CONTINUING
    assert updated.status_override == SeriesStatusOverride.CONTINUING
    assert updated.year_end is None
    metadata.derive_series_end_year.assert_not_awaited()
    metadata.refresh_series.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_override_refreshes_linked_series_from_comicvine(db_session) -> None:  # type: ignore[no-untyped-def]
    metadata = SimpleNamespace(
        derive_series_end_year=AsyncMock(),
        refresh_series=AsyncMock(),
        infer_series_status=AsyncMock(),
    )
    service = _service(metadata)
    series = Series(
        comicvine_id=12345,
        title="Linked Series",
        sort_title="Linked Series",
        year_start=2024,
        status=SeriesStatus.ENDED,
        status_override=SeriesStatusOverride.ENDED,
        series_type=SeriesType.STANDARD,
    )
    db_session.add(series)
    await db_session.flush()
    metadata.refresh_series.return_value = series

    updated = await service.set_status_override(db_session, series.id, None)

    assert updated is series
    assert updated.status_override is None
    metadata.refresh_series.assert_awaited_once_with(db_session, series.id, force=True)
    metadata.infer_series_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_override_infers_unlinked_series_locally(db_session) -> None:  # type: ignore[no-untyped-def]
    metadata = SimpleNamespace(
        derive_series_end_year=AsyncMock(),
        refresh_series=AsyncMock(),
        infer_series_status=AsyncMock(),
    )
    service = _service(metadata)
    series = Series(
        title="Unlinked Series",
        sort_title="Unlinked Series",
        year_start=2024,
        status=SeriesStatus.ENDED,
        status_override=SeriesStatusOverride.ENDED,
        series_type=SeriesType.STANDARD,
    )
    db_session.add(series)
    await db_session.flush()

    updated = await service.set_status_override(db_session, series.id, None)

    assert updated is series
    assert updated.status_override is None
    metadata.infer_series_status.assert_awaited_once_with(db_session, series)
    metadata.refresh_series.assert_not_awaited()
