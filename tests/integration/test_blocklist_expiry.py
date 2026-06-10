"""
Integration tests for blocklist expiry cleanup task.

Validates that entries older than the configured expiry period are
deleted, and that the expiry setting is respected.

Run:
    pytest tests/integration/test_blocklist_expiry.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title
from pullbox.models.config import SystemConfig
from pullbox.tasks.blocklist_task import cleanup_expired_blocklist

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ───────────────────────────────────────────────────────────


async def _seed_entry(
    session: AsyncSession,
    title: str,
    *,
    reason: BlocklistReason = BlocklistReason.FAILED,
    age_days: int = 0,
) -> BlocklistEntry:
    """Create a blocklist entry and backdate its created_at."""
    entry = BlocklistEntry(
        release_title=title,
        release_title_normalized=normalize_release_title(title),
        reason=reason,
    )
    session.add(entry)
    await session.flush()

    if age_days > 0:
        backdated = datetime.now(UTC) - timedelta(days=age_days)
        await session.execute(
            update(BlocklistEntry).where(BlocklistEntry.id == entry.id).values(created_at=backdated)
        )
        await session.flush()
        await session.refresh(entry)

    return entry


async def _set_config(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(SystemConfig, key)
    if existing:
        existing.value = value
    else:
        session.add(SystemConfig(key=key, value=value, value_type="string"))
    await session.flush()


async def _count_entries(session: AsyncSession) -> int:
    result = await session.execute(select(BlocklistEntry))
    return len(list(result.scalars().all()))


# ── Expiry task tests ─────────────────────────────────────────────────


@pytest.mark.slow
class TestExpiryHappyPath:
    """Entries older than expiry_days are deleted."""

    async def test_old_entries_deleted(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "90")
        await _seed_entry(db_session, "Old Release 1", age_days=100)
        await _seed_entry(db_session, "Old Release 2", age_days=95)
        await _seed_entry(db_session, "New Release", age_days=10)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 2

    async def test_boundary_entry_deleted(self, db_session: AsyncSession) -> None:
        """Entry exactly at the cutoff age is deleted."""
        await _set_config(db_session, "blocklist.expiry_days", "90")
        await _seed_entry(db_session, "Boundary", age_days=90)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 1

    async def test_new_entries_kept(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "90")
        await _seed_entry(db_session, "Fresh 1", age_days=1)
        await _seed_entry(db_session, "Fresh 2", age_days=45)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 0


@pytest.mark.slow
class TestExpiryConfiguration:
    """Expiry period is configurable."""

    async def test_custom_30_days(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "30")
        await _seed_entry(db_session, "Old 35d", age_days=35)
        await _seed_entry(db_session, "New 20d", age_days=20)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 1

    async def test_custom_365_days(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "365")
        await _seed_entry(db_session, "Old 400d", age_days=400)
        await _seed_entry(db_session, "New 300d", age_days=300)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 1

    async def test_zero_disables_expiry(self, db_session: AsyncSession) -> None:
        """expiry_days=0 means entries never expire."""
        await _set_config(db_session, "blocklist.expiry_days", "0")
        await _seed_entry(db_session, "Very Old", age_days=1000)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 0

    async def test_one_day_expiry(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "1")
        await _seed_entry(db_session, "Yesterday", age_days=2)
        await _seed_entry(db_session, "Today", age_days=0)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 1


@pytest.mark.slow
class TestExpiryEdgeCases:
    """Edge cases for the expiry task."""

    async def test_empty_table(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "90")
        count = await cleanup_expired_blocklist(db_session)

        assert count == 0

    async def test_all_expired(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "30")
        for i in range(5):
            await _seed_entry(db_session, f"Expired {i}", age_days=60 + i)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 5

    async def test_no_expired(self, db_session: AsyncSession) -> None:
        await _set_config(db_session, "blocklist.expiry_days", "90")
        for i in range(5):
            await _seed_entry(db_session, f"Fresh {i}", age_days=i)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 0

    async def test_second_run_returns_zero(self, db_session: AsyncSession) -> None:
        """Running twice removes on first run, returns 0 on second."""
        await _set_config(db_session, "blocklist.expiry_days", "30")
        await _seed_entry(db_session, "Expired Once", age_days=60)
        await db_session.commit()

        count1 = await cleanup_expired_blocklist(db_session)
        count2 = await cleanup_expired_blocklist(db_session)

        assert count1 == 1
        assert count2 == 0

    async def test_all_reasons_subject_to_expiry(self, db_session: AsyncSession) -> None:
        """Entries from all three reasons expire equally."""
        await _set_config(db_session, "blocklist.expiry_days", "30")
        await _seed_entry(db_session, "Failed Old", reason=BlocklistReason.FAILED, age_days=60)
        await _seed_entry(db_session, "Rejected Old", reason=BlocklistReason.REJECTED, age_days=60)
        await _seed_entry(db_session, "Manual Old", reason=BlocklistReason.MANUAL, age_days=60)
        count = await cleanup_expired_blocklist(db_session)

        assert count == 3
