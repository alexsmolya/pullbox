"""Closed artifact-host settings service tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.core.encryption import _get_fernet, is_encrypted
from pullbox.core.exceptions import ValidationError
from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectHostAccountState,
    DirectHostConfig,
)
from pullbox.services.direct_host_settings import (
    list_direct_host_settings,
    update_direct_host_setting,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator


@pytest.fixture(autouse=True)
def _deterministic_application_secret() -> Iterator[None]:
    provider = MagicMock()
    provider.secret_key.return_value = "direct-host-settings-test-secret"
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


@pytest.mark.asyncio
async def test_list_exposes_every_closed_host_without_writing_defaults(
    session: AsyncSession,
) -> None:
    settings = await list_direct_host_settings(session)

    assert [setting.host_kind for setting in settings] == list(DirectArtifactHostKind)
    assert all(setting.id is None for setting in settings)
    assert all(setting.enabled is False for setting in settings)
    assert settings[1].allowed_credential_fields == ("api_key",)


@pytest.mark.asyncio
async def test_update_creates_encrypted_write_only_host_setting(
    session: AsyncSession,
) -> None:
    setting = await update_direct_host_setting(
        session,
        DirectArtifactHostKind.PIXELDRAIN,
        enabled=True,
        preference=10,
        credential_updates={"api_key": "private-pixeldrain-key"},
    )

    assert setting.id is not None
    assert setting.enabled is True
    assert setting.preference == 10
    assert setting.account_state is DirectHostAccountState.UNKNOWN
    assert setting.credentials_configured is True
    assert setting.configured_credential_fields == ("api_key",)
    assert "private-pixeldrain-key" not in repr(setting)
    stored = await session.get(DirectHostConfig, setting.id)
    assert stored is not None
    assert is_encrypted(str(stored.encrypted_credentials["api_key"]))


@pytest.mark.asyncio
async def test_update_preserves_secret_when_only_preference_changes(
    session: AsyncSession,
) -> None:
    created = await update_direct_host_setting(
        session,
        DirectArtifactHostKind.MEGA,
        enabled=True,
        preference=50,
        credential_updates={"session": "revocable-session"},
    )

    updated = await update_direct_host_setting(
        session,
        DirectArtifactHostKind.MEGA,
        enabled=None,
        preference=5,
        credential_updates=None,
    )

    assert updated.id == created.id
    assert updated.enabled is True
    assert updated.preference == 5
    assert updated.configured_credential_fields == ("session",)


@pytest.mark.asyncio
async def test_required_account_host_cannot_be_enabled_without_session(
    session: AsyncSession,
) -> None:
    with pytest.raises(ValidationError, match="requires an account session"):
        await update_direct_host_setting(
            session,
            DirectArtifactHostKind.TERABOX,
            enabled=True,
            preference=50,
            credential_updates=None,
        )

    settings = await list_direct_host_settings(session)
    terabox = next(
        setting for setting in settings if setting.host_kind is DirectArtifactHostKind.TERABOX
    )
    assert terabox.id is None
    assert terabox.enabled is False
