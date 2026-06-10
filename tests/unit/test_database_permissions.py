"""Unit tests for SQLite database startup hardening and session lifecycle.

Tests cover permission setting on SQLite files, skipping non-SQLite URLs,
handling nonexistent files, graceful failure on permission errors, stale
WAL/SHM recovery, and the async session generator (get_db) commit/rollback
behavior.

Run:
    pytest tests/unit/test_database_permissions.py -v
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.database import (
    GateAwareAsyncSession,
    _recover_sqlite_sidecars_if_needed,
    _resolve_sqlite_journal_mode,
    _set_db_permissions,
    _set_sqlite_pragma,
    _sqlite_db_file_from_url,
    dispose_engine,
    get_db,
)
from pullbox.models import Base
from pullbox.models.config import SystemConfig

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-db-tests")


class TestSqlitePermissions:
    """Tests for _set_db_permissions()."""

    def test_sqlite_permissions_set(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        db_file.write_text("test")
        # Ensure it starts with broader permissions
        db_file.chmod(0o644)

        _set_db_permissions(f"sqlite+aiosqlite:///{db_file}")

        mode = db_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_non_sqlite_url_skipped(self) -> None:
        # Should not raise any errors
        _set_db_permissions("postgresql+asyncpg://user:pass@localhost/pullbox")

    def test_nonexistent_file_skipped(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "nonexistent.db"
        # Should not raise any errors
        _set_db_permissions(f"sqlite+aiosqlite:///{fake_path}")

    def test_permission_failure_logs_warning(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        db_file.write_text("test")

        with patch.object(Path, "chmod", side_effect=OSError("Permission denied")):
            # Should not raise — just logs a warning
            _set_db_permissions(f"sqlite+aiosqlite:///{db_file}")

    def test_handles_query_params(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        db_file.write_text("test")
        db_file.chmod(0o644)

        _set_db_permissions(f"sqlite+aiosqlite:///{db_file}?check_same_thread=False")

        mode = db_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_triple_slash_url(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        db_file.write_text("test")
        db_file.chmod(0o644)

        _set_db_permissions(f"sqlite+aiosqlite:///{db_file}")

        mode = db_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_double_slash_url_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """URL with :// (no triple slash) takes the elif branch."""
        db_file = tmp_path / "test.db"
        db_file.write_text("test")
        db_file.chmod(0o644)

        # Use a relative URL to hit the elif branch (no triple slash)
        monkeypatch.chdir(tmp_path)
        _set_db_permissions("sqlite+aiosqlite://test.db")

        mode = db_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_no_scheme_separator_skipped(self) -> None:
        # Malformed URL without :// — should skip gracefully
        _set_db_permissions("sqlite_no_scheme_test")


class TestSqliteStartupRecovery:
    """Tests for SQLite startup file probing and sidecar recovery."""

    def test_sqlite_db_file_from_url_parses_query_params(self, tmp_path: Path) -> None:
        db_file = tmp_path / "pullbox.db"

        parsed = _sqlite_db_file_from_url(f"sqlite+aiosqlite:///{db_file}?check_same_thread=False")

        assert parsed == db_file

    def test_sidecars_moved_when_main_db_is_readable_immutable(self, tmp_path: Path) -> None:
        db_file = tmp_path / "pullbox.db"
        db_file.write_text("sqlite")
        wal_file = tmp_path / "pullbox.db-wal"
        shm_file = tmp_path / "pullbox.db-shm"
        wal_file.write_text("wal")
        shm_file.write_text("shm")

        with patch(
            "pullbox.database._probe_sqlite_file",
            side_effect=[
                (False, "disk I/O error"),
                (True, None),
                (True, None),
            ],
        ):
            _recover_sqlite_sidecars_if_needed(f"sqlite+aiosqlite:///{db_file}")

        recovery_dirs = sorted(tmp_path.glob("recovery_*"))
        assert len(recovery_dirs) == 1
        recovery_dir = recovery_dirs[0]
        assert not wal_file.exists()
        assert not shm_file.exists()
        assert (recovery_dir / wal_file.name).read_text() == "wal"
        assert (recovery_dir / shm_file.name).read_text() == "shm"

    def test_skips_recovery_when_error_is_not_disk_io(self, tmp_path: Path) -> None:
        db_file = tmp_path / "pullbox.db"
        db_file.write_text("sqlite")
        wal_file = tmp_path / "pullbox.db-wal"
        wal_file.write_text("wal")

        with patch(
            "pullbox.database._probe_sqlite_file",
            return_value=(False, "database is locked"),
        ):
            _recover_sqlite_sidecars_if_needed(f"sqlite+aiosqlite:///{db_file}")

        assert wal_file.exists()
        assert not list(tmp_path.glob("recovery_*"))


class TestSqlitePragmas:
    """Tests for SQLite connection pragma setup and journal fallback."""

    def test_invalid_journal_mode_defaults_to_wal(self) -> None:
        """Config-driven journal mode should be allowlisted before PRAGMA use."""
        with patch(
            "pullbox.database.get_settings",
            return_value=type(
                "Settings",
                (),
                {"sqlite_journal_mode": "WAL; DROP TABLE series; --"},
            )(),
        ):
            assert _resolve_sqlite_journal_mode() == "WAL"

    def test_journal_mode_falls_back_to_delete_on_disk_io(self) -> None:
        class FakeCursor:
            def __init__(self) -> None:
                self.commands: list[str] = []

            def execute(self, command: str) -> None:
                self.commands.append(command)
                if command == "PRAGMA journal_mode=WAL":
                    raise sqlite3.OperationalError("disk I/O error")

            def close(self) -> None:
                return None

        class FakeConnection:
            def __init__(self) -> None:
                self._cursor = FakeCursor()

            def cursor(self) -> FakeCursor:
                return self._cursor

        FakeConnection.__module__ = "sqlite3"

        connection = FakeConnection()
        with patch(
            "pullbox.database.get_settings",
            return_value=type("Settings", (), {"sqlite_journal_mode": "WAL"})(),
        ):
            _set_sqlite_pragma(connection, object())

        assert connection._cursor.commands == [
            "PRAGMA journal_mode=WAL",
            "PRAGMA journal_mode=DELETE",
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=15000",
            "PRAGMA synchronous=NORMAL",
        ]

    def test_non_wal_journal_mode_does_not_fallback(self) -> None:
        class FakeCursor:
            def __init__(self) -> None:
                self.commands: list[str] = []

            def execute(self, command: str) -> None:
                self.commands.append(command)

            def close(self) -> None:
                return None

        class FakeConnection:
            def __init__(self) -> None:
                self._cursor = FakeCursor()

            def cursor(self) -> FakeCursor:
                return self._cursor

        FakeConnection.__module__ = "sqlite3"

        connection = FakeConnection()
        with patch(
            "pullbox.database.get_settings",
            return_value=type("Settings", (), {"sqlite_journal_mode": "DELETE"})(),
        ):
            _set_sqlite_pragma(connection, object())

        assert connection._cursor.commands[0] == "PRAGMA journal_mode=DELETE"

    def test_skips_recovery_when_immutable_probe_fails(self, tmp_path: Path) -> None:
        db_file = tmp_path / "pullbox.db"
        db_file.write_text("sqlite")
        wal_file = tmp_path / "pullbox.db-wal"
        wal_file.write_text("wal")

        with patch(
            "pullbox.database._probe_sqlite_file",
            side_effect=[
                (False, "disk I/O error"),
                (False, "disk image is malformed"),
            ],
        ):
            _recover_sqlite_sidecars_if_needed(f"sqlite+aiosqlite:///{db_file}")

        assert wal_file.exists()
        assert not list(tmp_path.glob("recovery_*"))


class TestGetDbSession:
    """Tests for the get_db() async session generator."""

    @pytest.fixture
    async def _mock_engine(self) -> None:
        """Patch database module globals with a test engine and factory."""
        import pullbox.database as db_mod

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)

        orig_engine = db_mod._engine
        orig_factory = db_mod._session_factory
        db_mod._engine = engine
        db_mod._session_factory = factory
        yield
        db_mod._engine = orig_engine
        db_mod._session_factory = orig_factory
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_db_yields_session(self, _mock_engine: None) -> None:
        """get_db() should yield a usable session and commit on success."""
        async for session in get_db():
            assert isinstance(session, AsyncSession)
            # The session should be usable
            result = await session.execute(__import__("sqlalchemy").text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_get_db_rolls_back_on_exception(self, _mock_engine: None) -> None:
        """get_db() should roll back on exception."""
        with pytest.raises(ValueError, match="test error"):
            async for _session in get_db():
                raise ValueError("test error")


class TestGateAwareAsyncSession:
    """Tests for maintenance gating on direct session factory usage."""

    @pytest.mark.asyncio
    async def test_direct_session_waits_for_maintenance_gate(self) -> None:
        import pullbox.database as db_mod

        db_mod._maintenance_gate = asyncio.Event()
        db_mod._maintenance_gate.set()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=GateAwareAsyncSession,
        )

        db_mod._maintenance_gate.clear()
        try:
            async with factory() as session:
                query_task = asyncio.create_task(session.execute(text("SELECT 1")))
                await asyncio.sleep(0.05)
                assert not query_task.done()

                db_mod._maintenance_gate.set()
                result = await query_task
                assert result.scalar() == 1
        finally:
            db_mod._maintenance_gate = asyncio.Event()
            db_mod._maintenance_gate.set()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_direct_session_refresh_waits_for_maintenance_gate(self) -> None:
        import pullbox.database as db_mod

        db_mod._maintenance_gate = asyncio.Event()
        db_mod._maintenance_gate.set()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=GateAwareAsyncSession,
        )

        db_mod._maintenance_gate.clear()
        try:
            async with factory() as session:
                config = SystemConfig(
                    key="maintenance-refresh-test",
                    value="true",
                    value_type="bool",
                )
                session.add(config)
                db_mod._maintenance_gate.set()
                await session.flush()

                db_mod._maintenance_gate.clear()
                refresh_task = asyncio.create_task(session.refresh(config))
                await asyncio.sleep(0.05)
                assert not refresh_task.done()

                db_mod._maintenance_gate.set()
                await refresh_task
        finally:
            db_mod._maintenance_gate = asyncio.Event()
            db_mod._maintenance_gate.set()
            await engine.dispose()


class TestDisposeEngine:
    """Tests for dispose_engine()."""

    @pytest.mark.asyncio
    async def test_dispose_engine_clears_globals(self) -> None:
        """dispose_engine() should reset _engine and _session_factory."""
        import pullbox.database as db_mod

        # Set up a temporary engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        orig_engine = db_mod._engine
        orig_factory = db_mod._session_factory
        db_mod._engine = engine
        db_mod._session_factory = factory

        await dispose_engine()

        assert db_mod._engine is None
        assert db_mod._session_factory is None

        # Restore originals (both should be None now anyway)
        db_mod._engine = orig_engine
        db_mod._session_factory = orig_factory

    @pytest.mark.asyncio
    async def test_dispose_noop_when_no_engine(self) -> None:
        """dispose_engine() should be safe to call with no engine."""
        import pullbox.database as db_mod

        orig_engine = db_mod._engine
        orig_factory = db_mod._session_factory
        db_mod._engine = None
        db_mod._session_factory = None

        # Should not raise
        await dispose_engine()

        db_mod._engine = orig_engine
        db_mod._session_factory = orig_factory
