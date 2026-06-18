"""Direct branch coverage for system API route orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from pullbox.api.v1 import system as system_api
from pullbox.core.exceptions import NotFoundError, ValidationError
from pullbox.models.config import SystemConfig
from pullbox.services.backup_service import BackupInfo
from pullbox.services.update_check import UpdateCheckResult, UpdateCheckService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _request(session_factory: object | None = "factory") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=session_factory))
    )


def _backup_info(filename: str = "pullbox_backup_20260617_120000.zip") -> BackupInfo:
    return BackupInfo(
        filename=filename,
        created_at="2026-06-17T12:00:00+00:00",
        size_bytes=4096,
        pullbox_version="0.9.5",
        db_size_bytes=1024,
        backup_type="manual",
    )


def _update_result() -> UpdateCheckResult:
    return UpdateCheckResult(
        current_version="0.9.5",
        latest_version="1.0.0",
        update_available=True,
        checked_at=datetime(2026, 6, 17, tzinfo=UTC),
        release_url="https://github.com/pullboxapp/pullbox/releases/tag/v1.0.0",
        release_notes="release notes",
        release_date="2026-06-17",
    )


@pytest.mark.asyncio
async def test_get_backup_service_uses_runtime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system_api,
        "get_settings",
        lambda: SimpleNamespace(backup_dir=Path("/tmp/backups")),
    )
    monkeypatch.setattr(system_api, "_resolve_db_path", lambda: Path("/tmp/pullbox.db"))

    service = await system_api._get_backup_service(object())

    assert service._backup_dir == Path("/tmp/backups")
    assert service._db_path == Path("/tmp/pullbox.db")


def test_resolve_db_path_handles_url_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    values = [
        ("sqlite+aiosqlite:////data/pullbox.db", Path("/data/pullbox.db")),
        ("sqlite://relative/pullbox.db", Path("relative/pullbox.db")),
        ("/plain/pullbox.db", Path("/plain/pullbox.db")),
    ]
    for db_url, expected in values:
        monkeypatch.setattr(
            "pullbox.config.get_settings",
            lambda db_url=db_url: SimpleNamespace(db_url=db_url),
        )
        assert system_api._resolve_db_path() == expected


@pytest.mark.asyncio
async def test_usage_stats_helpers_create_and_reuse_instance_id(
    db_session: AsyncSession,
) -> None:
    assert system_api._normalize_usage_stats_consent("unexpected") == "unknown"

    default_pref = await system_api.get_usage_stats_preference(object(), db_session)
    assert default_pref.consent == "unknown"
    assert default_pref.prompt_pending is True

    created = await system_api._ensure_usage_stats_instance_id(db_session)
    assert created
    assert await system_api._ensure_usage_stats_instance_id(db_session) == created

    row = await db_session.get(SystemConfig, "usage_stats_consent")
    if row is None:
        row = SystemConfig(key="usage_stats_consent", value="nonsense", value_type="string")
        db_session.add(row)
    else:
        row.value = "nonsense"
    await db_session.flush()

    normalized = await system_api._read_usage_stats_preference(db_session)
    assert normalized.consent == "unknown"


@pytest.mark.asyncio
async def test_update_usage_stats_preference_transitions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue_ping = AsyncMock()
    monkeypatch.setattr(system_api, "queue_usage_stats_ping", queue_ping)

    enabled = await system_api.update_usage_stats_preference(
        system_api.UsageStatsPreferenceUpdate(enabled=True),
        _request("session-factory"),
        object(),
        db_session,
    )
    assert enabled.enabled is True
    queue_ping.assert_awaited_once_with(session_factory="session-factory")

    queue_ping.reset_mock()
    disabled = await system_api.update_usage_stats_preference(
        system_api.UsageStatsPreferenceUpdate(enabled=False),
        _request("session-factory"),
        object(),
        db_session,
    )
    assert disabled.consent == "disabled"
    queue_ping.assert_not_awaited()


class _BackupService:
    def __init__(self, *, delete_result: bool = True, restore_result: bool = True) -> None:
        self.delete_result = delete_result
        self.restore_result = restore_result
        self.created: list[str] = []
        self.restored: list[str] = []
        self.deleted: list[str] = []

    async def create_backup(self, *, backup_type: str) -> BackupInfo:
        self.created.append(backup_type)
        return _backup_info()

    def list_backups(self) -> list[BackupInfo]:
        return [_backup_info("one.zip"), _backup_info("two.zip")]

    def get_backup_path(self, filename: str) -> Path | None:
        if filename == "missing.zip":
            return None
        return Path("/tmp") / filename

    def delete_backup(self, filename: str) -> bool:
        self.deleted.append(filename)
        return self.delete_result

    async def restore_backup(self, filename: str) -> bool:
        self.restored.append(filename)
        return self.restore_result


@pytest.mark.asyncio
async def test_backup_routes_cover_list_download_delete_and_errors(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _BackupService(delete_result=True)

    async def get_backup_service(_session: AsyncSession) -> _BackupService:
        return service

    monkeypatch.setattr(system_api, "_get_backup_service", get_backup_service)

    listed = await system_api.list_backups(object(), db_session)
    assert [item.filename for item in listed] == ["one.zip", "two.zip"]

    download = await system_api.download_backup("one.zip", object(), db_session)
    assert download.filename == "one.zip"
    with pytest.raises(NotFoundError):
        await system_api.download_backup("missing.zip", object(), db_session)
    with pytest.raises(ValidationError):
        await system_api.download_backup("../evil.zip", object(), db_session)

    assert await system_api.delete_backup("one.zip", object(), db_session) == {
        "message": "Backup deleted: one.zip"
    }
    service.delete_result = False
    with pytest.raises(NotFoundError):
        await system_api.delete_backup("two.zip", object(), db_session)
    with pytest.raises(ValidationError):
        await system_api.delete_backup("../evil.zip", object(), db_session)


@pytest.mark.asyncio
async def test_restart_system_schedules_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SimpleNamespace(schedule_restart=Mock())
    monkeypatch.setattr(system_api, "shutdown_manager", manager)

    response = await system_api.restart_system(object())

    assert response["restart_initiated"] is True
    manager.schedule_restart.assert_called_once_with()


@pytest.mark.asyncio
async def test_update_status_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pullbox.app.get_update_check_service", lambda: object())
    assert await system_api.get_update_status(object()) == {
        "checked": False,
        "error": "Update check service not initialized",
    }
    assert await system_api.check_for_update(object()) == {
        "checked": False,
        "error": "Update check service not initialized",
    }

    service = UpdateCheckService()
    monkeypatch.setattr("pullbox.app.get_update_check_service", lambda: service)
    service.check_for_update = AsyncMock(side_effect=RuntimeError("network down"))  # type: ignore[method-assign]
    assert await system_api.get_update_status(object()) == {"checked": False}

    service.check_for_update = AsyncMock(return_value=None)  # type: ignore[method-assign]
    assert await system_api.get_update_status(object()) == {"checked": False}
    assert await system_api.check_for_update(object()) == {
        "checked": False,
        "error": "Unable to reach GitHub",
    }

    result = _update_result()
    service._cached_result = result
    returned = await system_api.get_update_status(object())
    assert returned["checked"] is True
    assert returned["latest_version"] == "1.0.0"
    assert returned["checked_at"] == "2026-06-17T00:00:00+00:00"

    service.check_for_update = AsyncMock(return_value=result)  # type: ignore[method-assign]
    forced = await system_api.check_for_update(object())
    assert forced["release_notes"] == "release notes"


@pytest.mark.asyncio
async def test_comics_directory_routes_map_service_results(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_set_comics_directory(_session: AsyncSession, path: Path) -> SimpleNamespace:
        if path.name == "bad":
            raise ValueError("not a usable comics directory")
        return SimpleNamespace(path=str(path), id=42)

    async def fake_get_comics_directory(_session: AsyncSession) -> Path | None:
        return Path("/comics")

    monkeypatch.setattr(
        "pullbox.services.library_service.set_comics_directory",
        fake_set_comics_directory,
    )
    monkeypatch.setattr(
        "pullbox.services.library_service.get_comics_directory",
        fake_get_comics_directory,
    )

    response = await system_api.set_comics_dir(
        system_api.ComicsDirectoryRequest(path="/comics"),
        object(),
        db_session,
    )
    assert response.path == "/comics"
    assert response.library_root_id == 42
    assert await system_api.get_comics_dir(object(), db_session) == {"path": "/comics"}

    with pytest.raises(HTTPException) as exc_info:
        await system_api.set_comics_dir(
            system_api.ComicsDirectoryRequest(path="/bad"),
            object(),
            db_session,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_task_routes_cover_statuses(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Scheduler:
        def __init__(self) -> None:
            self.status = "queued"
            self.loaded = False

        async def load_persisted_stats(self, _session: AsyncSession) -> None:
            self.loaded = True

        def get_scheduled_tasks(self) -> list[dict[str, str]]:
            return [{"id": "metadata"}]

        def run_task_now(self, _task_id: str) -> str | None:
            return self.status

    scheduler = Scheduler()
    monkeypatch.setattr("pullbox.core.scheduler.get_scheduler", lambda: scheduler)

    listed = await system_api.list_tasks(object(), db_session)
    assert scheduler.loaded is True
    assert listed["scheduled"] == [{"id": "metadata"}]

    for status, expected in [
        ("already_running", "already running"),
        ("already_queued", "already queued"),
        ("queued", "queued"),
    ]:
        scheduler.status = status
        response = await system_api.run_task("metadata", object())
        assert response["status"] == status
        assert expected in response["message"]

    scheduler.status = None
    with pytest.raises(NotFoundError):
        await system_api.run_task("missing", object())


@pytest.mark.asyncio
async def test_download_diagnostic_package_writes_file_response(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_diagnostic_package(_session: AsyncSession) -> tuple[bytes, str]:
        return b"zip-bytes", "pullbox-diagnostic.zip"

    monkeypatch.setattr(
        "pullbox.services.diagnostic_service.create_diagnostic_package",
        fake_create_diagnostic_package,
    )

    response = await system_api.download_diagnostic_package(object(), db_session)

    assert response.filename == "pullbox-diagnostic.zip"
    assert Path(response.path).read_bytes() == b"zip-bytes"
    await response.background()
    assert not Path(response.path).exists()


@pytest.mark.asyncio
async def test_debug_logging_wrappers_delegate(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        system_api,
        "check_and_clear_expired_debug_logging_override",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        system_api,
        "get_debug_logging_status_response",
        AsyncMock(return_value="status"),
    )
    monkeypatch.setattr(
        system_api,
        "enable_debug_logging_response",
        AsyncMock(return_value="enabled"),
    )
    monkeypatch.setattr(
        system_api,
        "disable_debug_logging_response",
        AsyncMock(return_value="disabled"),
    )

    assert await system_api._check_and_clear_expired_override(db_session) is True
    assert await system_api.get_debug_logging_status(object(), db_session) == "status"
    body = SimpleNamespace()
    assert await system_api.enable_debug_logging(body, object(), db_session) == "enabled"
    assert await system_api.disable_debug_logging(object(), db_session) == "disabled"
