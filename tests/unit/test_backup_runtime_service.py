"""Tests for async backup runtime orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest

from pullbox.services.backup_runtime_service import BackupRuntimeService
from pullbox.services.backup_service import BackupInfo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runtime_service(tmp_path: Path) -> BackupRuntimeService:
    return BackupRuntimeService(
        backup_dir=tmp_path / "backups",
        db_path=tmp_path / "pullbox.db",
    )


class TestBackupRuntimeService:
    @pytest.mark.asyncio
    async def test_create_backup_uses_maintenance_window_and_thread_offload(
        self,
        runtime_service: BackupRuntimeService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        expected = BackupInfo(
            filename="backup.zip",
            created_at="2026-05-02T00:00:00+00:00",
            size_bytes=123,
            pullbox_version="0.0.0",
            db_size_bytes=120,
            backup_type="manual",
        )
        reasons: list[str] = []
        thread_call: dict[str, object] = {}

        @asynccontextmanager
        async def _fake_window(*, reason: str):  # type: ignore[no-untyped-def]
            reasons.append(reason)
            yield

        async def _fake_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
            thread_call["func"] = func
            thread_call["args"] = args
            thread_call["kwargs"] = kwargs
            return func(*args, **kwargs)

        def _fake_create_backup(*, backup_type: str) -> BackupInfo:
            assert backup_type == "manual"
            return expected

        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.database_maintenance_window",
            _fake_window,
        )
        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.asyncio.to_thread",
            _fake_to_thread,
        )
        monkeypatch.setattr(runtime_service.service, "create_backup", _fake_create_backup)

        result = await runtime_service.create_backup(backup_type="manual")

        assert result is expected
        assert reasons == ["backup"]
        assert thread_call["kwargs"] == {"backup_type": "manual"}

    @pytest.mark.asyncio
    async def test_restore_backup_uses_restore_maintenance_window(
        self,
        runtime_service: BackupRuntimeService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reasons: list[str] = []
        thread_call: dict[str, object] = {}

        @asynccontextmanager
        async def _fake_window(*, reason: str):  # type: ignore[no-untyped-def]
            reasons.append(reason)
            yield

        async def _fake_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
            thread_call["func"] = func
            thread_call["args"] = args
            thread_call["kwargs"] = kwargs
            return func(*args, **kwargs)

        def _fake_restore_backup(filename: str) -> bool:
            assert filename == "backup.zip"
            return True

        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.database_maintenance_window",
            _fake_window,
        )
        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.asyncio.to_thread",
            _fake_to_thread,
        )
        monkeypatch.setattr(runtime_service.service, "restore_backup", _fake_restore_backup)

        restored = await runtime_service.restore_backup("backup.zip")

        assert restored is True
        assert reasons == ["restore_backup"]
        assert thread_call["args"] == ("backup.zip",)

    @pytest.mark.asyncio
    async def test_cleanup_old_backups_uses_thread_offload_without_maintenance(
        self,
        runtime_service: BackupRuntimeService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        thread_call: dict[str, object] = {}

        def _unexpected_window(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("cleanup should not enter maintenance window")

        async def _fake_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
            thread_call["func"] = func
            thread_call["args"] = args
            thread_call["kwargs"] = kwargs
            return func(*args, **kwargs)

        def _fake_cleanup_old_backups(*, retention_days: int) -> int:
            assert retention_days == 28
            return 3

        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.database_maintenance_window",
            _unexpected_window,
        )
        monkeypatch.setattr(
            "pullbox.services.backup_runtime_service.asyncio.to_thread",
            _fake_to_thread,
        )
        monkeypatch.setattr(
            runtime_service.service,
            "cleanup_old_backups",
            _fake_cleanup_old_backups,
        )

        deleted = await runtime_service.cleanup_old_backups(retention_days=28)

        assert deleted == 3
        assert thread_call["kwargs"] == {"retention_days": 28}

    def test_service_property_returns_underlying_backup_service(
        self,
        runtime_service: BackupRuntimeService,
    ) -> None:
        assert runtime_service.service is runtime_service._service
