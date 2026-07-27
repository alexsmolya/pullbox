"""Write-only secret and read-model contracts for resolver configuration."""

from unittest.mock import MagicMock, patch

import pytest

from pullbox.core.encryption import _get_fernet
from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import DirectResolverConfig, DirectResolverState
from pullbox.services.direct_resolver_configuration import (
    load_resolver_auth_headers,
    read_resolver_config,
    update_resolver_auth_headers,
)


@pytest.fixture(autouse=True)
def _deterministic_application_secret() -> None:
    provider = MagicMock()
    provider.secret_key.return_value = "direct-resolver-test-secret"
    _get_fernet.cache_clear()
    with patch("pullbox.core.config_file.get_config_provider", return_value=provider):
        yield
    _get_fernet.cache_clear()


def _config() -> DirectResolverConfig:
    return DirectResolverConfig(
        name="default",
        endpoint="http://resolver:8191",
        enabled=True,
        state=DirectResolverState.HEALTHY,
        allow_private_http=True,
    )


def test_resolver_auth_headers_are_encrypted_and_read_projection_is_secret_free() -> None:
    config = _config()

    update_resolver_auth_headers(
        config,
        {
            "Authorization": "Bearer resolver-secret",
            "X-API-Key": "resolver-api-secret",
        },
    )

    stored = str(config.encrypted_auth_headers)
    assert "resolver-secret" not in stored
    assert "resolver-api-secret" not in stored
    assert all(str(value).startswith("enc:") for value in config.encrypted_auth_headers.values())
    material = load_resolver_auth_headers(config)
    assert material.headers == {
        "Authorization": "Bearer resolver-secret",
        "X-API-Key": "resolver-api-secret",
    }

    projection = read_resolver_config(config)
    assert projection.auth_header_names == ("Authorization", "X-API-Key")
    assert projection.auth_headers_configured is True
    assert "secret" not in repr(projection).lower()
    assert not hasattr(projection, "authentication_headers")


def test_resolver_auth_header_updates_are_merge_or_clear_only() -> None:
    config = _config()
    update_resolver_auth_headers(config, {"Authorization": "Bearer first"})
    update_resolver_auth_headers(
        config,
        {"Authorization": None, "X-API-Key": "replacement"},
    )

    assert load_resolver_auth_headers(config).headers == {"X-API-Key": "replacement"}
    assert config.state is DirectResolverState.UNKNOWN
    assert config.last_tested_at is None
    assert config.last_error_code is None


@pytest.mark.parametrize(
    "headers",
    [
        {"Cookie": "session=bad"},
        {"Host": "attacker.invalid"},
        {"Content-Length": "100"},
        {"Proxy-Authorization": "secret"},
        {"Bad Header": "secret"},
        {"X-One": "1", "X-Two": "2", "X-Three": "3", "X-Four": "4", "X-Five": "5"},
    ],
)
def test_resolver_rejects_unsafe_or_unbounded_auth_headers(
    headers: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        update_resolver_auth_headers(_config(), headers)


def test_resolver_config_repr_never_contains_plaintext_headers() -> None:
    config = _config()
    update_resolver_auth_headers(config, {"Authorization": "Bearer do-not-log"})

    assert "do-not-log" not in repr(load_resolver_auth_headers(config))
