"""Tests for What's New upstream refresh behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.services.whats_new_data_client import PullboxDataClientError
from pullbox.services.whats_new_refresh_service import WhatsNewRefreshService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _SuccessfulClient:
    async def get_current_week(self) -> dict[str, object]:
        return {
            "store_date": "2026-05-13",
            "count": 1,
            "issues": [
                {
                    "locg_issue_id": 1511525,
                    "store_date": "2026-05-13",
                    "release_week_date": "2026-05-06",
                }
            ],
        }

    async def get_upcoming(self) -> dict[str, object]:
        return {"weeks": [], "lookahead_weeks": 8}


class _FailingClient:
    async def get_current_week(self) -> dict[str, object]:
        msg = "upstream unavailable"
        raise PullboxDataClientError(msg)

    async def get_upcoming(self) -> dict[str, object]:
        return {"weeks": [], "lookahead_weeks": 8}


async def test_refresh_populates_current_week_and_upcoming_cache(
    db_session: AsyncSession,
) -> None:
    service = WhatsNewRefreshService(client=_SuccessfulClient())

    result = await service.refresh(db_session)

    assert result.current_week_count == 1
    assert result.upcoming_week_count == 0
    assert result.upcoming_release_count == 0

    current = await service.cache.get_current_week(db_session, result.current_week_store_date)
    upcoming = await service.cache.get_upcoming(db_session)
    assert current is not None
    assert current.payload["count"] == 1
    issues = current.payload["issues"]
    assert isinstance(issues, list)
    assert issues[0]["release_week_date"] == "2026-05-06"
    assert upcoming is not None
    assert upcoming.payload["lookahead_weeks"] == 8


async def test_refresh_raises_without_writing_partial_cache(
    db_session: AsyncSession,
) -> None:
    service = WhatsNewRefreshService(client=_FailingClient())

    with pytest.raises(PullboxDataClientError):
        await service.refresh(db_session)

    assert await service.cache.get_latest_current_week(db_session) is None
    assert await service.cache.get_upcoming(db_session) is None
