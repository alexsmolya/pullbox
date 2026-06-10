"""Unit tests for local-auth-bypass configuration validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pullbox.api.v1.config import update_config
from pullbox.core.exceptions import ValidationError
from pullbox.models.config import SystemConfig
from pullbox.models.user import User
from pullbox.schemas.config import ConfigUpdate


def _mock_request() -> MagicMock:
    request = MagicMock()
    request.client.host = "127.0.0.1"
    return request


class TestLocalAuthBypassConfigValidation:
    """Validate explicit identity and address rules for local auth bypass."""

    @pytest.mark.asyncio
    async def test_invalid_local_bypass_address_is_rejected(self, db_session) -> None:
        with pytest.raises(ValidationError, match="Invalid local bypass address or CIDR"):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(values={"local_auth_bypass_addresses": "127.0.0.1, nope"}),
                _user=MagicMock(id=1, username="admin"),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_enabling_bypass_requires_specific_user_when_multiple_active_users(
        self,
        db_session,
    ) -> None:
        db_session.add_all(
            [
                User(username="admin", password_hash="hash", is_active=True),
                User(username="ops", password_hash="hash", is_active=True),
            ]
        )
        await db_session.commit()

        with pytest.raises(
            ValidationError,
            match="must target a specific active username when more than one active account exists",
        ):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(
                    values={
                        "local_auth_bypass_enabled": "true",
                        "local_auth_bypass_addresses": "127.0.0.1",
                        "local_auth_bypass_username": "",
                    }
                ),
                _user=MagicMock(id=1, username="admin"),
                session=db_session,
            )

    @pytest.mark.asyncio
    async def test_enabling_bypass_accepts_valid_explicit_username(self, db_session) -> None:
        db_session.add_all(
            [
                User(username="admin", password_hash="hash", is_active=True),
                User(username="ops", password_hash="hash", is_active=True),
            ]
        )
        await db_session.commit()

        await update_config(
            request=_mock_request(),
            body=ConfigUpdate(
                values={
                    "local_auth_bypass_enabled": "true",
                    "local_auth_bypass_addresses": "127.0.0.1, 192.168.1.9/24",
                    "local_auth_bypass_username": "ops",
                }
            ),
            _user=MagicMock(id=1, username="admin"),
            session=db_session,
        )

        enabled = await db_session.get(SystemConfig, "local_auth_bypass_enabled")
        addresses = await db_session.get(SystemConfig, "local_auth_bypass_addresses")
        username = await db_session.get(SystemConfig, "local_auth_bypass_username")

        assert enabled is not None
        assert addresses is not None
        assert username is not None
        assert enabled.value == "true"
        assert addresses.value == "127.0.0.1, 192.168.1.0/24"
        assert username.value == "ops"

    @pytest.mark.asyncio
    async def test_enabling_bypass_requires_addresses(self, db_session) -> None:
        user = User(username="admin", password_hash="hash", is_active=True)
        db_session.add(user)
        await db_session.commit()

        with pytest.raises(
            ValidationError,
            match="requires at least one trusted local address or CIDR",
        ):
            await update_config(
                request=_mock_request(),
                body=ConfigUpdate(
                    values={
                        "local_auth_bypass_enabled": "true",
                        "local_auth_bypass_addresses": "",
                    }
                ),
                _user=MagicMock(id=1, username="admin"),
                session=db_session,
            )
