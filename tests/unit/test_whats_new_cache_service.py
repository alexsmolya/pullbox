"""Tests for What's New release cache helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache
from pullbox.services.whats_new_cache_service import (
    FRESH_CACHE_LABEL,
    STALE_CACHE_LABEL,
    WhatsNewCacheService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _fixed_now() -> datetime:
    return datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


class TestWhatsNewCacheService:
    async def test_upsert_current_week_creates_cache_row(self, db_session: AsyncSession) -> None:
        service = WhatsNewCacheService(now_func=_fixed_now)

        row = await service.upsert_current_week(
            db_session,
            store_date=date(2026, 5, 13),
            payload={"count": 1, "issues": [{"title": "Absolute Flash #1"}]},
        )
        await db_session.flush()

        assert row.cache_key == "current-week:2026-05-13"
        assert row.cache_kind == WhatsNewCacheKind.CURRENT_WEEK
        assert row.store_date == date(2026, 5, 13)
        assert row.payload["count"] == 1
        assert row.fetched_at == _fixed_now()
        assert row.last_successful_refresh_at == _fixed_now()

    async def test_upsert_updates_existing_row_without_duplicates(
        self, db_session: AsyncSession
    ) -> None:
        service = WhatsNewCacheService(now_func=_fixed_now)

        first = await service.upsert_upcoming(
            db_session,
            payload={"weeks": [{"label": "old"}]},
            publisher="DC Comics",
        )
        await db_session.flush()
        second = await service.upsert_upcoming(
            db_session,
            payload={"weeks": [{"label": "new"}]},
            publisher="DC Comics",
        )
        await db_session.flush()

        total = await db_session.scalar(select(func.count()).select_from(WhatsNewReleaseCache))
        assert first.id == second.id
        assert total == 1
        assert second.cache_key == "upcoming:dc-comics"
        assert second.payload == {"weeks": [{"label": "new"}]}

    async def test_get_latest_successful_refresh_returns_newest_timestamp(
        self, db_session: AsyncSession
    ) -> None:
        now = _fixed_now()
        service = WhatsNewCacheService(now_func=lambda: now)
        db_session.add_all(
            [
                WhatsNewReleaseCache(
                    cache_key="current-week:2026-05-06",
                    cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                    store_date=date(2026, 5, 6),
                    payload={},
                    fetched_at=now - timedelta(days=10),
                    last_successful_refresh_at=now - timedelta(days=10),
                ),
                WhatsNewReleaseCache(
                    cache_key="upcoming:all",
                    cache_kind=WhatsNewCacheKind.UPCOMING,
                    payload={},
                    fetched_at=now - timedelta(hours=2),
                    last_successful_refresh_at=now - timedelta(hours=2),
                ),
            ]
        )
        await db_session.flush()

        latest = await service.get_latest_successful_refresh(db_session)

        assert latest == now - timedelta(hours=2)

    async def test_get_latest_current_week_returns_newest_store_date(
        self, db_session: AsyncSession
    ) -> None:
        now = _fixed_now()
        service = WhatsNewCacheService(now_func=lambda: now)
        older = WhatsNewReleaseCache(
            cache_key="current-week:2026-05-06",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 5, 6),
            payload={"store_date": "2026-05-06", "count": 1, "issues": []},
            fetched_at=now - timedelta(days=7),
            last_successful_refresh_at=now - timedelta(days=7),
        )
        newer = WhatsNewReleaseCache(
            cache_key="current-week:2026-05-13",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 5, 13),
            payload={"store_date": "2026-05-13", "count": 2, "issues": []},
            fetched_at=now - timedelta(days=1),
            last_successful_refresh_at=now - timedelta(days=1),
        )
        db_session.add_all([older, newer])
        await db_session.flush()

        latest = await service.get_latest_current_week(db_session)

        assert latest == newer

    async def test_stale_status_and_labels_are_based_on_fetched_at(
        self, db_session: AsyncSession
    ) -> None:
        now = _fixed_now()
        service = WhatsNewCacheService(now_func=lambda: now, stale_after=timedelta(hours=6))
        fresh = WhatsNewReleaseCache(
            cache_key="current-week:2026-05-13",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 5, 13),
            payload={},
            fetched_at=now - timedelta(hours=2),
            last_successful_refresh_at=now - timedelta(hours=2),
        )
        stale = WhatsNewReleaseCache(
            cache_key="upcoming:all",
            cache_kind=WhatsNewCacheKind.UPCOMING,
            payload={},
            fetched_at=now - timedelta(hours=7),
            last_successful_refresh_at=now - timedelta(hours=7),
        )

        assert service.is_stale(fresh) is False
        assert service.cache_status_label(fresh) == FRESH_CACHE_LABEL
        assert service.is_stale(stale) is True
        assert service.cache_status_label(stale) == STALE_CACHE_LABEL

    async def test_cleanup_retention_removes_old_rows_and_preserves_recent(
        self, db_session: AsyncSession
    ) -> None:
        now = _fixed_now()
        service = WhatsNewCacheService(now_func=lambda: now)
        old = WhatsNewReleaseCache(
            cache_key="current-week:2026-04-01",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 4, 1),
            payload={},
            fetched_at=now - timedelta(days=60),
            last_successful_refresh_at=now - timedelta(days=60),
        )
        recent = WhatsNewReleaseCache(
            cache_key="current-week:2026-05-13",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 5, 13),
            payload={},
            fetched_at=now - timedelta(days=3),
            last_successful_refresh_at=now - timedelta(days=3),
        )
        db_session.add_all([old, recent])
        await db_session.flush()

        deleted = await service.cleanup_retention(db_session, retention_days=30)
        remaining = (await db_session.scalars(select(WhatsNewReleaseCache))).all()

        assert deleted == 1
        assert [row.cache_key for row in remaining] == ["current-week:2026-05-13"]

    async def test_lookup_helpers_return_expected_cache_rows(
        self, db_session: AsyncSession
    ) -> None:
        service = WhatsNewCacheService(now_func=_fixed_now)
        current = await service.upsert_current_week(
            db_session,
            store_date=date(2026, 5, 13),
            payload={"count": 1},
        )
        upcoming = await service.upsert_upcoming(db_session, payload={"weeks": []})
        await db_session.flush()

        assert await service.get_current_week(db_session, date(2026, 5, 13)) == current
        assert await service.get_upcoming(db_session) == upcoming
