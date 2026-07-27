"""Security contracts for direct provider and artifact-host configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.core.encryption import _get_fernet, is_encrypted
from pullbox.core.exceptions import ValidationError
from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectHostAccountState,
    DirectHostConfig,
    DirectProviderConfig,
)
from pullbox.services.direct_configuration_service import (
    clear_provider_bearer_token,
    load_host_credential_material,
    load_provider_secret_material,
    read_host_config,
    read_provider_config,
    update_host_credentials,
    update_provider_configuration_secrets,
    write_provider_bearer_token,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(autouse=True)
def _deterministic_application_secret() -> None:
    provider = MagicMock()
    provider.secret_key.return_value = "direct-download-test-secret"
    _get_fernet.cache_clear()
    with patch("pullbox.core.config_file.get_config_provider", return_value=provider):
        yield
    _get_fernet.cache_clear()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


def _provider() -> DirectProviderConfig:
    return DirectProviderConfig(
        provider_id="community.getcomics",
        display_name="GetComics Community Provider",
        endpoint="https://provider.example.test",
    )


def _host(
    kind: DirectArtifactHostKind = DirectArtifactHostKind.PIXELDRAIN,
) -> DirectHostConfig:
    return DirectHostConfig(host_kind=kind)


def test_provider_secret_writes_encrypt_values_and_active_load_decrypts_them() -> None:
    config = _provider()

    write_provider_bearer_token(config, "provider-bearer-token")
    update_provider_configuration_secrets(
        config,
        {"member_key": "source-member-key", "session_token": "source-session"},
    )

    assert config.encrypted_bearer_token is not None
    assert is_encrypted(config.encrypted_bearer_token)
    assert all(is_encrypted(str(value)) for value in config.encrypted_configuration.values())

    material = load_provider_secret_material(config)
    assert material.bearer_token == "provider-bearer-token"
    assert material.configuration == {
        "member_key": "source-member-key",
        "session_token": "source-session",
    }


def test_provider_read_projection_exposes_presence_but_never_secret_values() -> None:
    config = _provider()
    write_provider_bearer_token(config, "provider-bearer-token")
    update_provider_configuration_secrets(config, {"member_key": "source-member-key"})

    view = read_provider_config(config)
    rendered = repr(view)

    assert view.bearer_token_configured is True
    assert view.configuration_secret_fields == ("member_key",)
    assert "provider-bearer-token" not in rendered
    assert "source-member-key" not in rendered
    assert "enc:" not in rendered
    assert "provider-bearer-token" not in repr(load_provider_secret_material(config))
    assert "source-member-key" not in repr(load_provider_secret_material(config))


def test_provider_secret_updates_merge_and_explicit_empty_values_clear() -> None:
    config = _provider()
    write_provider_bearer_token(config, "provider-bearer-token")
    update_provider_configuration_secrets(
        config,
        {"member_key": "first", "session_token": "second"},
    )

    update_provider_configuration_secrets(
        config,
        {"member_key": "rotated", "session_token": None},
    )
    clear_provider_bearer_token(config)

    material = load_provider_secret_material(config)
    assert material.bearer_token is None
    assert material.configuration == {"member_key": "rotated"}
    assert read_provider_config(config).configuration_secret_fields == ("member_key",)


@pytest.mark.parametrize("field_name", ["", "token value", "../token", "A" * 65])
def test_provider_secret_field_names_are_bounded_and_non_executable(field_name: str) -> None:
    config = _provider()
    original = config.encrypted_configuration

    with pytest.raises(ValidationError, match="secret field name"):
        update_provider_configuration_secrets(config, {field_name: "secret"})

    assert config.encrypted_configuration is original


def test_secret_write_rejects_caller_supplied_ciphertext_without_mutating_config() -> None:
    config = _provider()
    write_provider_bearer_token(config, "original")
    original_ciphertext = config.encrypted_bearer_token

    with pytest.raises(ValidationError, match="plaintext secret value"):
        write_provider_bearer_token(config, "enc:caller-controlled")

    assert config.encrypted_bearer_token == original_ciphertext


def test_host_credential_writes_encrypt_merge_and_clear_values() -> None:
    config = _host()

    update_host_credentials(config, {"api_key": "pixeldrain-key"})

    assert config.account_state == DirectHostAccountState.UNKNOWN
    assert is_encrypted(str(config.encrypted_credentials["api_key"]))
    assert load_host_credential_material(config).credentials == {"api_key": "pixeldrain-key"}
    assert read_host_config(config).credential_fields == ("api_key",)

    update_host_credentials(config, {"api_key": ""})

    assert config.encrypted_credentials == {}
    assert config.account_state == DirectHostAccountState.NOT_CONFIGURED
    assert read_host_config(config).credentials_configured is False


def test_credentialless_hosts_reject_secret_storage() -> None:
    config = _host(DirectArtifactHostKind.ROOTZ)
    original = config.encrypted_credentials

    with pytest.raises(ValidationError, match="does not accept credentials"):
        update_host_credentials(config, {"api_key": "not-supported"})

    assert config.encrypted_credentials is original


def test_host_read_projection_and_secret_material_repr_are_redacted() -> None:
    config = _host(DirectArtifactHostKind.MEGA)
    update_host_credentials(config, {"session": "mega-session-secret"})

    view = read_host_config(config)
    material = load_host_credential_material(config)

    assert view.credentials_configured is True
    assert view.credential_fields == ("session",)
    assert "mega-session-secret" not in repr(view)
    assert "mega-session-secret" not in repr(material)
    assert "enc:" not in repr(view)
    assert "enc:" not in repr(material)


def test_secret_material_fails_closed_when_application_key_changes() -> None:
    config = _host(DirectArtifactHostKind.MEGA)
    update_host_credentials(config, {"session": "mega-session-secret"})

    _get_fernet.cache_clear()
    with (
        patch(
            "pullbox.core.config_resolver.get_application_secret",
            return_value="different-application-secret",
        ),
        pytest.raises(ValueError, match="Failed to decrypt secret"),
    ):
        load_host_credential_material(config)


@pytest.mark.asyncio
async def test_database_rows_contain_ciphertext_but_not_plaintext(
    session: AsyncSession,
) -> None:
    provider = _provider()
    write_provider_bearer_token(provider, "provider-bearer-token")
    update_provider_configuration_secrets(provider, {"member_key": "source-member-key"})
    host = _host()
    update_host_credentials(host, {"api_key": "pixeldrain-key"})
    session.add_all([provider, host])
    await session.commit()

    provider_row = (
        await session.execute(
            text(
                "SELECT encrypted_bearer_token, encrypted_configuration "
                "FROM direct_provider_configs"
            )
        )
    ).one()
    host_row = (
        await session.execute(text("SELECT encrypted_credentials FROM direct_host_configs"))
    ).one()
    stored = repr((provider_row, host_row))

    assert "enc:" in stored
    assert "provider-bearer-token" not in stored
    assert "source-member-key" not in stored
    assert "pixeldrain-key" not in stored
