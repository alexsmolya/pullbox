"""Tests for application secret strength validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.config_file import ConfigFileError, ConfigFileProvider
from pullbox.core.config_resolver import get_application_secret
from pullbox.core.secret_validation import WeakApplicationSecretError, validate_application_secret

if TYPE_CHECKING:
    from pathlib import Path


def test_validate_application_secret_accepts_generated_secret_shape() -> None:
    validate_application_secret("a1b2c3d4" * 8)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "test",
        "secret",
        "change-me",
        "short-but-complex-Aa1!",
        "a" * 32,
    ],
)
def test_validate_application_secret_rejects_weak_values(
    secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", raising=False)
    with pytest.raises(WeakApplicationSecretError):
        validate_application_secret(secret)


def test_validate_application_secret_rejects_known_weak_long_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weak_long_value = "known-weak-secret-value-with-enough-length"
    monkeypatch.delenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", raising=False)
    monkeypatch.setattr(
        "pullbox.core.secret_validation._WEAK_APPLICATION_SECRETS",
        frozenset({weak_long_value}),
    )

    with pytest.raises(WeakApplicationSecretError, match="known weak value"):
        validate_application_secret(weak_long_value.upper())


def test_config_provider_rejects_weak_bootstrap_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULLBOX_SECRET_KEY", "change-me")
    monkeypatch.delenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", raising=False)
    from pullbox.config import get_settings

    get_settings.cache_clear()
    try:
        provider = ConfigFileProvider(tmp_path / "config.xml")
        with pytest.raises(ConfigFileError):
            provider.ensure_config_exists()
    finally:
        get_settings.cache_clear()


def test_config_provider_allows_weak_bootstrap_secret_when_tests_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULLBOX_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", "true")
    from pullbox.config import get_settings

    get_settings.cache_clear()
    try:
        provider = ConfigFileProvider(tmp_path / "config.xml")
        provider.ensure_config_exists()
        assert provider.secret_key() == "test-secret"
    finally:
        get_settings.cache_clear()


def test_application_secret_fallback_rejects_weak_runtime_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uninitialized-provider fallback must still validate env secrets."""

    def _uninitialized_provider() -> object:
        raise RuntimeError("provider not initialized")

    monkeypatch.setenv("PULLBOX_SECRET_KEY", "change-me")
    monkeypatch.delenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", raising=False)
    monkeypatch.setattr(
        "pullbox.core.config_resolver.get_config_provider",
        _uninitialized_provider,
    )
    from pullbox.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(WeakApplicationSecretError):
            get_application_secret()
    finally:
        get_settings.cache_clear()


def test_application_secret_fallback_accepts_strong_runtime_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strong runtime secrets remain valid before config.xml provider init."""
    secret = "correct-horse-battery-staple-for-pullbox-tests-2026"

    def _uninitialized_provider() -> object:
        raise RuntimeError("provider not initialized")

    monkeypatch.setenv("PULLBOX_SECRET_KEY", secret)
    monkeypatch.delenv("PULLBOX_ALLOW_WEAK_SECRET_FOR_TESTS", raising=False)
    monkeypatch.setattr(
        "pullbox.core.config_resolver.get_config_provider",
        _uninitialized_provider,
    )
    from pullbox.config import get_settings

    get_settings.cache_clear()
    try:
        assert get_application_secret() == secret
    finally:
        get_settings.cache_clear()
