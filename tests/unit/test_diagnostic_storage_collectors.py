"""Tests for diagnostic storage collectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.config import PullboxSettings
from pullbox.services.diagnostic_storage_collectors import collect_disk_and_permissions

if TYPE_CHECKING:
    from pathlib import Path


def _settings_for_tmp_path(tmp_path: Path) -> PullboxSettings:
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    library_root = tmp_path / "library"
    covers_dir = tmp_path / "covers"
    temp_dir = tmp_path / "tmp"
    backup_dir = tmp_path / "backups"
    for directory in (data_dir, logs_dir, library_root, covers_dir, temp_dir, backup_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (library_root / "comic.cbz").write_bytes(b"abc123")

    return PullboxSettings(
        db_url=f"sqlite+aiosqlite:///{data_dir / 'pullbox.db'}",
        data_dir=data_dir,
        logs_dir=logs_dir,
        library_root=library_root,
        covers_dir=covers_dir,
        temp_dir=temp_dir,
        backup_dir=backup_dir,
        secret_key="test-secret",
        startup_update_check_enabled=False,
        sqlite_journal_mode="DELETE",
    )


@pytest.mark.asyncio
async def test_collect_disk_and_permissions_reports_runtime_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings_for_tmp_path(tmp_path)
    monkeypatch.setattr("pullbox.config.get_settings", lambda: settings)

    result = await collect_disk_and_permissions(db_session)

    library = result["library_root"]
    assert library["path"] == str(settings.library_root)
    assert library["exists"] is True
    assert library["is_dir"] is True
    assert library["writable"] is True
    assert library["dir_size_bytes"] >= 6
    assert "disk_free_bytes" in library
    assert result["database_dir"]["path"] == str(settings.data_dir)
