"""Tests for diagnostic runtime/config collectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.config import PullboxSettings
from pullbox.services.diagnostic_runtime_collectors import (
    collect_bootstrap_settings,
    collect_config_xml_snapshot,
    collect_container_runtime,
)

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

    return PullboxSettings(
        db_url="sqlite+aiosqlite:///:memory:",
        data_dir=data_dir,
        logs_dir=logs_dir,
        library_root=library_root,
        covers_dir=covers_dir,
        temp_dir=temp_dir,
        backup_dir=backup_dir,
        secret_key="super-secret-bootstrap-key",
        comicvine_api_key="cv-secret",
        startup_update_check_enabled=False,
        sqlite_journal_mode="DELETE",
    )


def test_collect_config_xml_snapshot_redacts_secret_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings_for_tmp_path(tmp_path)
    monkeypatch.setattr("pullbox.config.get_settings", lambda: settings)
    (settings.data_dir / "config.xml").write_text(
        (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<Config>\n"
            "  <SecretKey>topsecret</SecretKey>\n"
            "  <BindAddress>0.0.0.0</BindAddress>\n"
            "</Config>\n"
        ),
        encoding="utf-8",
    )

    snapshot = collect_config_xml_snapshot()

    assert snapshot is not None
    name, payload = snapshot
    assert name == "config_xml.xml"
    text = payload.decode("utf-8")
    assert "[REDACTED]" in text
    assert "topsecret" not in text
    assert "0.0.0.0" in text


@pytest.mark.asyncio
async def test_runtime_collectors_sanitize_bootstrap_and_container_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings_for_tmp_path(tmp_path)
    monkeypatch.setattr("pullbox.config.get_settings", lambda: settings)

    bootstrap = await collect_bootstrap_settings()
    container = collect_container_runtime()

    assert bootstrap["secret_key"] == "[REDACTED]"
    assert bootstrap["comicvine_api_key"] == "[REDACTED]"
    assert container["config_xml_path"] == str(settings.data_dir / "config.xml")
    assert container["mount_paths"]["library_root"] == str(settings.library_root)
