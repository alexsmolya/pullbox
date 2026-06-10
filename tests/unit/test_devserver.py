from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

from pullbox import devserver


def _runtime_settings() -> SimpleNamespace:
    return SimpleNamespace(
        bind_address="127.0.0.1",
        port=8585,
        data_dir="/tmp/pullbox-data",
        db_url="sqlite+aiosqlite:////tmp/pullbox.db",
    )


class TestDevserverStartupUpdateCheck:
    def test_devserver_disables_startup_update_check_by_default(self, monkeypatch) -> None:
        devserver.get_settings.cache_clear()
        monkeypatch.delenv("PULLBOX_STARTUP_UPDATE_CHECK_ENABLED", raising=False)

        with (
            patch("pullbox.devserver.ensure_host_secret"),
            patch("pullbox.devserver._resolve_db_path", return_value="/tmp/pullbox.db"),
            patch("pullbox.devserver.get_settings", return_value=_runtime_settings()),
            patch("uvicorn.run"),
            patch("sys.argv", ["pullbox.devserver"]),
        ):
            devserver.main()

        assert os.environ["PULLBOX_STARTUP_UPDATE_CHECK_ENABLED"] == "false"

    def test_devserver_preserves_explicit_startup_update_check_override(self, monkeypatch) -> None:
        devserver.get_settings.cache_clear()
        monkeypatch.setenv("PULLBOX_STARTUP_UPDATE_CHECK_ENABLED", "true")

        with (
            patch("pullbox.devserver.ensure_host_secret"),
            patch("pullbox.devserver._resolve_db_path", return_value="/tmp/pullbox.db"),
            patch("pullbox.devserver.get_settings", return_value=_runtime_settings()),
            patch("uvicorn.run"),
            patch("sys.argv", ["pullbox.devserver"]),
        ):
            devserver.main()

        assert os.environ["PULLBOX_STARTUP_UPDATE_CHECK_ENABLED"] == "true"


class TestDevserverAutoMigrate:
    def test_devserver_enables_auto_migrate_by_default(self, monkeypatch) -> None:
        devserver.get_settings.cache_clear()
        monkeypatch.delenv("PULLBOX_DEV_AUTO_MIGRATE", raising=False)

        with (
            patch("pullbox.devserver.ensure_host_secret"),
            patch("pullbox.devserver._resolve_db_path", return_value="/tmp/pullbox.db"),
            patch("pullbox.devserver.get_settings", return_value=_runtime_settings()),
            patch("uvicorn.run"),
            patch("sys.argv", ["pullbox.devserver"]),
        ):
            devserver.main()

        assert os.environ["PULLBOX_DEV_AUTO_MIGRATE"] == "true"

    def test_devserver_preserves_auto_migrate_override(self, monkeypatch) -> None:
        devserver.get_settings.cache_clear()
        monkeypatch.setenv("PULLBOX_DEV_AUTO_MIGRATE", "false")

        with (
            patch("pullbox.devserver.ensure_host_secret"),
            patch("pullbox.devserver._resolve_db_path", return_value="/tmp/pullbox.db"),
            patch("pullbox.devserver.get_settings", return_value=_runtime_settings()),
            patch("uvicorn.run"),
            patch("sys.argv", ["pullbox.devserver"]),
        ):
            devserver.main()

        assert os.environ["PULLBOX_DEV_AUTO_MIGRATE"] == "false"
