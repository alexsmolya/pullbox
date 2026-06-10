"""Tests for first-run config.xml generation in the secret-only model."""

from __future__ import annotations

import re
import stat
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import pytest  # noqa: TC002

from pullbox.core.config_file import ConfigFileProvider

if TYPE_CHECKING:
    from pathlib import Path


def _parse_config(path: Path) -> dict[str, str]:
    tree = ET.parse(path)
    root = tree.getroot()
    return {child.tag: (child.text or "").strip() for child in root}


class TestFirstRunGeneration:
    """Auto-generation creates a valid secret-only config.xml file."""

    def test_generate_creates_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)

        assert provider.ensure_config_exists() is True
        assert config_path.exists()

    def test_generate_includes_secret_key_only(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.ensure_config_exists()

        values = _parse_config(config_path)
        assert set(values.keys()) == {"SecretKey"}
        assert len(values["SecretKey"]) > 0

    def test_generated_secret_key_is_128_hex_chars(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("PULLBOX_SECRET_KEY", raising=False)
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            config_path = tmp_path / "config.xml"
            provider = ConfigFileProvider(config_path)
            provider.ensure_config_exists()
            secret = _parse_config(config_path)["SecretKey"]
            assert len(secret) == 128
            assert re.fullmatch(r"[0-9a-f]+", secret)
        finally:
            get_settings.cache_clear()

    def test_generate_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        config_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<Config><SecretKey>my-key</SecretKey></Config>",
            encoding="utf-8",
        )
        provider = ConfigFileProvider(config_path)

        assert provider.ensure_config_exists() is False
        assert _parse_config(config_path)["SecretKey"] == "my-key"

    def test_generate_sets_permissions_600(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.ensure_config_exists()

        permissions = stat.S_IMODE(config_path.stat().st_mode)
        assert permissions == 0o600

    def test_generate_creates_parent_directories(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nested" / "deep" / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.ensure_config_exists()
        assert config_path.exists()

    def test_generate_valid_xml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.ensure_config_exists()

        tree = ET.parse(config_path)
        assert tree.getroot().tag == "Config"


class TestBootstrapSecretMigration:
    """First-run generation seeds the secret from bootstrap settings when present."""

    def test_migrate_secret_key_from_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "env-secret-key-123")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            config_path = tmp_path / "config.xml"
            provider = ConfigFileProvider(config_path)
            provider.ensure_config_exists()
            assert _parse_config(config_path)["SecretKey"] == "env-secret-key-123"
        finally:
            get_settings.cache_clear()

    def test_existing_config_not_modified_by_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "new-env-key")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            config_path = tmp_path / "config.xml"
            config_path.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                "<Config><SecretKey>original-key</SecretKey></Config>",
                encoding="utf-8",
            )
            provider = ConfigFileProvider(config_path)
            provider.ensure_config_exists()
            assert _parse_config(config_path)["SecretKey"] == "original-key"
        finally:
            get_settings.cache_clear()
