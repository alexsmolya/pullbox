"""Tests for the secret-only ``config.xml`` provider contract."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import pytest

from pullbox.core.config_file import (
    CONFIG_XML_KEYS,
    ConfigFileError,
    ConfigFileProvider,
    get_config_provider,
    init_config_provider,
    is_config_xml_key,
)

if TYPE_CHECKING:
    from pathlib import Path


SAMPLE_CONFIG_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Config>
  <SecretKey>abc123</SecretKey>
  <BindAddress>0.0.0.0</BindAddress>
  <Port>8585</Port>
  <BaseUrl>https://legacy.example.com</BaseUrl>
  <InstanceName>LegacyBox</InstanceName>
</Config>
"""


def _write_config(path: Path, content: str = SAMPLE_CONFIG_XML) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestConfigFileProviderRead:
    """Read behavior for the secret-only config.xml contract."""

    def test_read_secret_key(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        assert provider.get("secret_key") == "abc123"

    def test_legacy_fields_are_not_exposed(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        assert provider.get("bind_address") is None
        assert provider.get("port") is None
        assert provider.get("base_url") is None
        assert provider.get("instance_name") is None

    def test_missing_key_returns_default(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        assert provider.get("nonexistent", "fallback") == "fallback"

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        assert provider.get("nonexistent") is None

    def test_malformed_xml_raises(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml", "<<<not xml>>>"))
        with pytest.raises(ConfigFileError):
            provider.get("secret_key")

    def test_xml_entities_are_rejected(self, tmp_path: Path) -> None:
        xml = """\
<!DOCTYPE Config [
  <!ENTITY injected "not-a-real-secret">
]>
<Config><SecretKey>&injected;</SecretKey></Config>
"""
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml", xml))

        with pytest.raises(ConfigFileError):
            provider.get("secret_key")


class TestConfigFileProviderWrite:
    """Write behavior for the active secret-only contract."""

    def test_set_secret_key_creates_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.set("secret_key", "new-secret")

        assert config_path.exists()
        assert provider.get("secret_key") == "new-secret"

    def test_set_preserves_other_elements(self, tmp_path: Path) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        provider.set("secret_key", "rotated-secret")

        assert provider.get("secret_key") == "rotated-secret"
        root = ET.parse(provider.config_path).getroot()
        assert root.findtext("InstanceName") == "LegacyBox"

    def test_save_dict_empty_is_noop(self, tmp_path: Path) -> None:
        config_path = _write_config(tmp_path / "config.xml")
        original = config_path.read_text()
        provider = ConfigFileProvider(config_path)
        provider.save_dict({})
        assert config_path.read_text() == original

    def test_written_file_permissions_are_600(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)
        provider.set("secret_key", "secure-secret")

        permissions = stat.S_IMODE(config_path.stat().st_mode)
        assert permissions == 0o600


class TestConfigFileProviderResolve:
    """Secret resolution honors bootstrap settings before config.xml."""

    def test_secret_key_env_overrides_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "env-secret")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            assert provider.resolve("secret_key") == "env-secret"
        finally:
            get_settings.cache_clear()

    def test_secret_key_reads_file_when_no_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = ConfigFileProvider(_write_config(tmp_path / "config.xml"))
        monkeypatch.delenv("PULLBOX_SECRET_KEY", raising=False)
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            assert provider.resolve("secret_key") == "abc123"
        finally:
            get_settings.cache_clear()


class TestConfigFileProviderGeneration:
    """First-run generation writes only the persistent secret."""

    def test_ensure_config_exists_creates_secret_only_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.xml"
        provider = ConfigFileProvider(config_path)

        assert provider.ensure_config_exists() is True

        content = config_path.read_text(encoding="utf-8")
        assert "<SecretKey>" in content
        assert "<BindAddress>" not in content
        assert "<Port>" not in content

    def test_ensure_config_exists_uses_bootstrap_secret(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PULLBOX_SECRET_KEY", "bootstrap-secret")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            config_path = tmp_path / "config.xml"
            provider = ConfigFileProvider(config_path)
            provider.ensure_config_exists()
            assert provider.get("secret_key") == "bootstrap-secret"
        finally:
            get_settings.cache_clear()

    def test_existing_config_is_not_overwritten(self, tmp_path: Path) -> None:
        config_path = _write_config(tmp_path / "config.xml")
        provider = ConfigFileProvider(config_path)

        assert provider.ensure_config_exists() is False
        assert provider.get("secret_key") == "abc123"


class TestConfigFileProviderMetadata:
    """Metadata helpers reflect the secret-only contract."""

    def test_config_xml_keys_are_secret_only(self) -> None:
        assert frozenset({"secret_key"}) == CONFIG_XML_KEYS

    def test_is_config_xml_key(self) -> None:
        assert is_config_xml_key("secret_key") is True
        assert is_config_xml_key("bind_address") is False


class TestConfigFileProviderSingleton:
    """Module-level provider lifecycle."""

    def test_init_and_get_provider(self, tmp_path: Path) -> None:
        provider = init_config_provider(tmp_path)
        assert provider is get_config_provider()
        assert provider.config_path == tmp_path / "config.xml"

    def test_get_provider_raises_before_init(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pullbox.core.config_file as config_file

        monkeypatch.setattr(config_file, "_provider", None)
        with pytest.raises(RuntimeError):
            get_config_provider()
