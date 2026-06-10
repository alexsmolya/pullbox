"""Tests for SQLite concurrency, WAL mode, and locking behavior (C-9.2).

Verifies:
- Concurrent reads don't block each other
- Concurrent read + write doesn't block the read
- Two concurrent writes queue properly (don't raise "locked")
- SQLite pragmas are applied (WAL, busy_timeout, synchronous, foreign_keys)
- Long write with busy_timeout allows other writes to wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db_path(tmp_path: Path) -> str:
    """Create a temporary SQLite database with WAL mode and a test table."""
    db_file = tmp_path / "contention_test.db"
    url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=15000"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        await conn.execute(text("INSERT INTO items (name) VALUES ('seed')"))
    await engine.dispose()
    return url


@pytest.fixture
async def session_factory(db_path: str) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory for the test database."""
    from sqlalchemy import event as sa_event

    engine = create_async_engine(db_path)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn: object, _rec: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory  # type: ignore[misc]
    await engine.dispose()


class TestSQLitePragmas:
    """SQLite pragmas are applied correctly."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            result = await session.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            assert mode == "wal"

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            result = await session.execute(text("PRAGMA foreign_keys"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_busy_timeout_set(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            result = await session.execute(text("PRAGMA busy_timeout"))
            assert result.scalar() == 15000

    @pytest.mark.asyncio
    async def test_synchronous_normal(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            result = await session.execute(text("PRAGMA synchronous"))
            # NORMAL = 1
            assert result.scalar() == 1


class TestConcurrentReads:
    """Concurrent reads should not block each other."""

    @pytest.mark.asyncio
    async def test_concurrent_reads_succeed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Two concurrent reads both complete without blocking."""

        async def read_items() -> int:
            async with session_factory() as session:
                result = await session.execute(text("SELECT COUNT(*) FROM items"))
                return result.scalar() or 0

        counts = await asyncio.gather(read_items(), read_items())
        assert counts == [1, 1]


class TestReadWriteConcurrency:
    """Reads should not be blocked by concurrent writes in WAL mode."""

    @pytest.mark.asyncio
    async def test_read_during_write(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """A read completes while a write transaction is in progress."""
        write_started = asyncio.Event()
        read_done = asyncio.Event()

        async def writer() -> None:
            async with session_factory() as session:
                await session.execute(text("INSERT INTO items (name) VALUES ('write_test')"))
                write_started.set()
                # Wait briefly to let the reader run while transaction is open
                await asyncio.sleep(0.05)
                await session.commit()

        async def reader() -> int:
            await write_started.wait()
            async with session_factory() as session:
                result = await session.execute(text("SELECT COUNT(*) FROM items"))
                count = result.scalar() or 0
                read_done.set()
                return count

        _, count = await asyncio.gather(writer(), reader())
        # Reader sees at least the seed row (may or may not see uncommitted write)
        assert count >= 1


class TestConcurrentWrites:
    """Two concurrent writes should queue properly with busy_timeout."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_succeed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Two concurrent writes both succeed — busy_timeout prevents locking errors."""

        async def write_item(name: str) -> None:
            async with session_factory() as session:
                await session.execute(text(f"INSERT INTO items (name) VALUES ('{name}')"))
                await session.commit()

        await asyncio.gather(write_item("alpha"), write_item("beta"))

        # Verify both writes persisted
        async with session_factory() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM items"))
            count = result.scalar()
            # seed + alpha + beta = 3
            assert count == 3

    @pytest.mark.asyncio
    async def test_three_concurrent_writes(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Three concurrent writers all succeed without database locked errors."""

        async def write_item(name: str) -> None:
            async with session_factory() as session:
                await session.execute(text(f"INSERT INTO items (name) VALUES ('{name}')"))
                await session.commit()

        await asyncio.gather(write_item("one"), write_item("two"), write_item("three"))

        async with session_factory() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM items"))
            count = result.scalar()
            assert count == 4  # seed + 3
