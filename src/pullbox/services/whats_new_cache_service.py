"""Read/write helpers for cached What's New release payloads."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

FRESH_CACHE_LABEL = "fresh"
STALE_CACHE_LABEL = "stale"
DEFAULT_STALE_AFTER = timedelta(hours=6)


class WhatsNewCacheService:
    """Owns local cache semantics for upstream release payloads."""

    def __init__(
        self,
        *,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
        now_func: Callable[[], datetime] | None = None,
    ) -> None:
        self._stale_after = stale_after
        self._now_func = now_func or _utc_now

    async def upsert_current_week(
        self,
        session: AsyncSession,
        *,
        store_date: date,
        payload: dict[str, Any],
    ) -> WhatsNewReleaseCache:
        """Create or replace the cache row for a current-week store date."""

        cache_key = current_week_cache_key(store_date)
        return await self._upsert(
            session,
            cache_key=cache_key,
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            payload=payload,
            store_date=store_date,
            publisher=None,
        )

    async def upsert_upcoming(
        self,
        session: AsyncSession,
        *,
        payload: dict[str, Any],
        publisher: str | None = None,
    ) -> WhatsNewReleaseCache:
        """Create or replace the cache row for upcoming releases."""

        cache_key = upcoming_cache_key(publisher)
        return await self._upsert(
            session,
            cache_key=cache_key,
            cache_kind=WhatsNewCacheKind.UPCOMING,
            payload=payload,
            store_date=None,
            publisher=publisher,
        )

    async def get_current_week(
        self,
        session: AsyncSession,
        store_date: date,
    ) -> WhatsNewReleaseCache | None:
        """Return the cached current-week payload for a store date."""

        result = await session.scalars(
            select(WhatsNewReleaseCache).where(
                WhatsNewReleaseCache.cache_key == current_week_cache_key(store_date)
            )
        )
        return result.one_or_none()

    async def get_latest_current_week(self, session: AsyncSession) -> WhatsNewReleaseCache | None:
        """Return the newest cached current-week payload by store date."""

        result = await session.scalars(
            select(WhatsNewReleaseCache)
            .where(WhatsNewReleaseCache.cache_kind == WhatsNewCacheKind.CURRENT_WEEK)
            .order_by(
                WhatsNewReleaseCache.store_date.desc(),
                WhatsNewReleaseCache.fetched_at.desc(),
            )
            .limit(1)
        )
        return result.one_or_none()

    async def get_upcoming(
        self,
        session: AsyncSession,
        publisher: str | None = None,
    ) -> WhatsNewReleaseCache | None:
        """Return the cached upcoming payload."""

        result = await session.scalars(
            select(WhatsNewReleaseCache).where(
                WhatsNewReleaseCache.cache_key == upcoming_cache_key(publisher)
            )
        )
        return result.one_or_none()

    async def get_latest_successful_refresh(self, session: AsyncSession) -> datetime | None:
        """Return the newest successful cache refresh timestamp."""

        return await session.scalar(
            select(func.max(WhatsNewReleaseCache.last_successful_refresh_at))
        )

    async def cleanup_retention(self, session: AsyncSession, *, retention_days: int) -> int:
        """Delete cache rows older than the retention window."""

        cutoff = self._now() - timedelta(days=retention_days)
        rows = (
            await session.scalars(
                select(WhatsNewReleaseCache).where(WhatsNewReleaseCache.fetched_at < cutoff)
            )
        ).all()
        for row in rows:
            await session.delete(row)
        return len(rows)

    def is_stale(self, row: WhatsNewReleaseCache) -> bool:
        """Return whether a cache row is older than the configured freshness window."""

        return self._now() - row.fetched_at > self._stale_after

    def cache_status_label(self, row: WhatsNewReleaseCache) -> str:
        """Return the small status label the UI can expose beside cached data."""

        if self.is_stale(row):
            return STALE_CACHE_LABEL
        return FRESH_CACHE_LABEL

    async def _upsert(
        self,
        session: AsyncSession,
        *,
        cache_key: str,
        cache_kind: WhatsNewCacheKind,
        payload: dict[str, Any],
        store_date: date | None,
        publisher: str | None,
    ) -> WhatsNewReleaseCache:
        now = self._now()
        row = await session.scalar(
            select(WhatsNewReleaseCache).where(WhatsNewReleaseCache.cache_key == cache_key)
        )
        if row is None:
            row = WhatsNewReleaseCache(
                cache_key=cache_key,
                cache_kind=cache_kind,
                store_date=store_date,
                publisher=publisher,
                payload=payload,
                fetched_at=now,
                last_successful_refresh_at=now,
            )
            session.add(row)
            return row

        row.cache_kind = cache_kind
        row.store_date = store_date
        row.publisher = publisher
        row.payload = payload
        row.fetched_at = now
        row.last_successful_refresh_at = now
        return row

    def _now(self) -> datetime:
        now = self._now_func()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)


def current_week_cache_key(store_date: date) -> str:
    """Return the stable cache key for a current-week store date."""

    return f"current-week:{store_date.isoformat()}"


def upcoming_cache_key(publisher: str | None = None) -> str:
    """Return the stable cache key for upcoming release payloads."""

    if publisher:
        normalized = publisher.strip().lower().replace(" ", "-")
        return f"upcoming:{normalized}"
    return "upcoming:all"


def _utc_now() -> datetime:
    return datetime.now(UTC)
