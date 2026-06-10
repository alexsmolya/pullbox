"""Tests for the local What's New release cache model."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TestWhatsNewReleaseCacheModel:
    async def test_current_week_payload_round_trips(self, db_session: AsyncSession) -> None:
        fetched_at = datetime(2026, 5, 16, 12, 30, tzinfo=UTC)
        row = WhatsNewReleaseCache(
            cache_key="current-week:2026-05-13",
            cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
            store_date=date(2026, 5, 13),
            payload={"count": 1, "issues": [{"title": "Absolute Flash #1"}]},
            fetched_at=fetched_at,
            last_successful_refresh_at=fetched_at,
        )

        db_session.add(row)
        await db_session.flush()
        await db_session.refresh(row)

        saved = await db_session.scalar(
            select(WhatsNewReleaseCache).where(
                WhatsNewReleaseCache.cache_key == "current-week:2026-05-13"
            )
        )

        assert saved is not None
        assert saved.cache_kind == WhatsNewCacheKind.CURRENT_WEEK
        assert saved.store_date == date(2026, 5, 13)
        assert saved.publisher is None
        assert saved.payload["issues"][0]["title"] == "Absolute Flash #1"
        assert saved.fetched_at == fetched_at
        assert saved.last_successful_refresh_at == fetched_at

    async def test_upcoming_cache_can_be_publisher_scoped(self, db_session: AsyncSession) -> None:
        fetched_at = datetime(2026, 5, 16, 12, 45, tzinfo=UTC)
        row = WhatsNewReleaseCache(
            cache_key="upcoming:dc-comics",
            cache_kind=WhatsNewCacheKind.UPCOMING,
            publisher="DC Comics",
            payload={"weeks": [], "lookahead_weeks": 8},
            fetched_at=fetched_at,
            last_successful_refresh_at=fetched_at,
        )

        db_session.add(row)
        await db_session.flush()
        await db_session.refresh(row)

        assert row.store_date is None
        assert row.publisher == "DC Comics"
        assert row.payload == {"weeks": [], "lookahead_weeks": 8}

    def test_table_contract_has_freshness_and_cleanup_indexes(self) -> None:
        table = WhatsNewReleaseCache.__table__
        indexes = {index.name for index in table.indexes}
        unique_constraints = {
            constraint.name for constraint in table.constraints if constraint.name
        }

        assert "uq_whats_new_release_cache_key" in unique_constraints
        assert "ix_whats_new_release_cache_kind" in indexes
        assert "ix_whats_new_release_cache_fetched_at" in indexes
        assert "ix_whats_new_release_cache_last_success" in indexes
        assert set(table.columns) >= {
            table.columns.cache_key,
            table.columns.cache_kind,
            table.columns.store_date,
            table.columns.publisher,
            table.columns.payload,
            table.columns.fetched_at,
            table.columns.last_successful_refresh_at,
        }
