"""Unit tests for authentication dependency injection (deps.py).

Tests the get_current_user dependency's session-cookie, API-key, and
local-bypass authentication paths with mocked dependencies.

Run:
    pytest tests/unit/test_deps_auth.py -v
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pullbox.api.deps import (
    _is_local_address,
    get_current_user,
    get_db_dep,
    require_auth,
    require_interactive_auth,
)

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-deps-tests")


class _Headers(dict):  # type: ignore[type-arg]
    """Dict subclass that allows overriding .get()."""


def _make_session(
    *,
    execute_results: list[MagicMock] | MagicMock | None = None,
) -> AsyncMock:
    """Create a mock async session whose execute() returns proper sync results.

    When ``execute_results`` is a list, successive awaits of ``session.execute()``
    return items from the list in order (``side_effect``).  When it is a single
    ``MagicMock``, every call returns that same object (``return_value``).
    When ``None``, a default result whose ``scalar_one_or_none()`` returns
    ``None`` is used — this prevents ``AsyncMock`` auto-children from leaking
    coroutine objects where sync values are expected.
    """
    session = AsyncMock()
    if execute_results is None:
        default_result = MagicMock()
        default_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=default_result)
    elif isinstance(execute_results, list):
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        session.execute = AsyncMock(return_value=execute_results)
    return session


def _make_request(
    *,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> MagicMock:
    """Create a mock Request object."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_host
    request.cookies = cookies or {}
    request.headers = _Headers(headers or {})
    request.state = MagicMock()
    return request


class TestGetCurrentUserSessionCookie:
    """Tests for session cookie authentication path."""

    @pytest.mark.asyncio
    async def test_valid_session_returns_user(self) -> None:
        """Valid session cookie should authenticate and set auth_method."""
        from pullbox.models.user import User
        from pullbox.services.auth_service import AuthService

        user = MagicMock(spec=User)
        user.id = 1
        user.session_version = 0
        user.is_active = True

        token = AuthService.create_session_token(1, session_version=0)
        request = _make_request(cookies={"pullbox_session": token})

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=token,
            )

        assert result is user
        assert request.state.auth_method == "session"

    @pytest.mark.asyncio
    async def test_session_validation_uses_configured_lifetime_window(self) -> None:
        """Session validation should honor the saved lifetime setting."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        user.id = 1
        user.session_version = 0
        user.is_active = True

        request = _make_request(cookies={"pullbox_session": "test-token"})
        session = _make_session()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        with (
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "",
                    "local_auth_bypass_enabled": "false",
                    "session_lifetime_hours": "3",
                },
            ),
            patch(
                "pullbox.api.deps.AuthService.validate_session_token",
                return_value={"user_id": 1, "sv": 0, "csrf": "token"},
            ) as mock_validate_session_token,
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session="test-token",
            )

        assert result is user
        mock_validate_session_token.assert_called_once_with(
            "test-token",
            max_age_seconds=10800,
        )

    @pytest.mark.asyncio
    async def test_invalid_session_returns_none(self) -> None:
        """Invalid session cookie should return None."""
        request = _make_request(cookies={"pullbox_session": "bad-token"})
        session = _make_session()

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session="bad-token",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_session_version_mismatch_returns_none(self) -> None:
        """Session with outdated version should be rejected."""
        from pullbox.models.user import User
        from pullbox.services.auth_service import AuthService

        user = MagicMock(spec=User)
        user.id = 1
        user.session_version = 5  # Token has version 0
        user.is_active = True

        token = AuthService.create_session_token(1, session_version=0)
        request = _make_request(cookies={"pullbox_session": token})

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=token,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_user_session_returns_none(self) -> None:
        """Session for deactivated user should return None."""
        from pullbox.models.user import User
        from pullbox.services.auth_service import AuthService

        user = MagicMock(spec=User)
        user.id = 1
        user.session_version = 0
        user.is_active = False

        token = AuthService.create_session_token(1, session_version=0)
        request = _make_request(cookies={"pullbox_session": token})

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=token,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_user_not_found_returns_none(self) -> None:
        """Session for deleted user should return None."""
        from pullbox.services.auth_service import AuthService

        token = AuthService.create_session_token(999, session_version=0)
        request = _make_request(cookies={"pullbox_session": token})

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=token,
            )

        assert result is None


class TestGetCurrentUserAPIKey:
    """Tests for API key authentication path."""

    @pytest.mark.asyncio
    async def test_valid_api_key_authenticates(self) -> None:
        """Valid API key should authenticate and set auth_method."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        user.id = 1
        request = _make_request(headers={"x-api-key": "pb_k1_testkey"})

        with (
            patch(
                "pullbox.api.deps.AuthService.validate_api_key",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "",
                    "local_auth_bypass_enabled": "false",
                    "session_lifetime_hours": "24",
                },
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=_make_session(),
                x_api_key="pb_k1_testkey",
                pullbox_session=None,
            )

        assert result is user
        assert request.state.auth_method == "api_key"
        assert request.state.csrf_token is None

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_none(self) -> None:
        """Invalid API key should fall through to None."""
        request = _make_request(headers={"x-api-key": "pb_k1_bad"})

        with (
            patch(
                "pullbox.api.deps.AuthService.validate_api_key",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=_make_session(),
                x_api_key="pb_k1_bad",
                pullbox_session=None,
            )

        assert result is None


class TestGetCurrentUserLocalBypass:
    """Tests for local auth bypass path."""

    @pytest.mark.asyncio
    async def test_local_bypass_authenticates(self) -> None:
        """Local bypass from configured address should auto-authenticate."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        user.id = 1
        user.username = "admin"
        user.is_active = True
        request = _make_request(client_host="192.168.1.50")

        user_list_result = MagicMock()
        user_list_result.scalars.return_value.all.return_value = [user]
        user_get_result = MagicMock()
        user_get_result.scalar_one_or_none.return_value = user
        session = _make_session(execute_results=[user_list_result, user_get_result])

        with (
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "192.168.1.0/24",
                    "local_auth_bypass_enabled": "true",
                    "local_auth_bypass_username": "",
                    "session_lifetime_hours": "24",
                },
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                trusted_proxies="",
            )
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=None,
            )

        assert result is user
        assert request.state.auth_method == "local_bypass"
        assert isinstance(request.state.csrf_token, str)
        assert request.state.csrf_token

    @pytest.mark.asyncio
    async def test_local_bypass_disabled(self) -> None:
        """Local bypass should not authenticate if config says disabled."""
        request = _make_request(client_host="192.168.1.50")

        with (
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "192.168.1.0/24",
                    "local_auth_bypass_enabled": "false",
                    "local_auth_bypass_username": "",
                    "session_lifetime_hours": "24",
                },
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=_make_session(),
                x_api_key=None,
                pullbox_session=None,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_local_bypass_uses_configured_username(self) -> None:
        """Local bypass should target the configured active username."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        user.id = 7
        user.username = "ops"
        user.is_active = True
        request = _make_request(client_host="192.168.1.50")

        configured_result = MagicMock()
        configured_result.scalar_one_or_none.return_value = user
        user_get_result = MagicMock()
        user_get_result.scalar_one_or_none.return_value = user
        session = _make_session(execute_results=[configured_result, user_get_result])

        with (
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "192.168.1.0/24",
                    "local_auth_bypass_enabled": "true",
                    "local_auth_bypass_username": "ops",
                    "session_lifetime_hours": "24",
                },
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=None,
            )

        assert result is user
        assert request.state.auth_method == "local_bypass"

    @pytest.mark.asyncio
    async def test_local_bypass_denied_when_multiple_users_and_no_username(self) -> None:
        """Local bypass should fail closed when identity would be ambiguous."""
        request = _make_request(client_host="192.168.1.50")

        user_list_result = MagicMock()
        user_list_result.scalars.return_value.all.return_value = [MagicMock(), MagicMock()]
        session = _make_session(execute_results=user_list_result)

        with (
            patch(
                "pullbox.api.deps.load_system_config_values",
                new_callable=AsyncMock,
                return_value={
                    "local_auth_bypass_addresses": "192.168.1.0/24",
                    "local_auth_bypass_enabled": "true",
                    "local_auth_bypass_username": "",
                    "session_lifetime_hours": "24",
                },
            ),
            patch("pullbox.api.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=None,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_auth_returns_none(self) -> None:
        """No auth credentials should return None."""
        request = _make_request()

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=_make_session(),
                x_api_key=None,
                pullbox_session=None,
            )

        assert result is None


class TestGetCurrentUserEdgeCases:
    """Edge cases for get_current_user."""

    @pytest.mark.asyncio
    async def test_non_int_session_version_treated_as_zero(self) -> None:
        """Non-integer sv in token should be treated as 0."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        user.id = 1
        user.session_version = 0
        user.is_active = True

        # Create a token with non-int sv
        from itsdangerous import URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer(os.environ.get("PULLBOX_SECRET_KEY", "test"))
        token = serializer.dumps({"user_id": 1, "csrf": "abc123", "sv": "not-int"})

        request = _make_request(cookies={"pullbox_session": token})
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=session,
                x_api_key=None,
                pullbox_session=token,
            )

        # token_sv becomes 0, user.session_version is 0 → should match
        assert result is user

    @pytest.mark.asyncio
    async def test_non_int_user_id_in_token_skipped(self) -> None:
        """Token with non-int user_id should be skipped."""
        from itsdangerous import URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer(os.environ.get("PULLBOX_SECRET_KEY", "test"))
        token = serializer.dumps({"user_id": "not-int", "csrf": "abc"})

        request = _make_request()

        with patch("pullbox.api.deps.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(local_addresses="", trusted_proxies="")
            result = await get_current_user(
                request=request,
                session=_make_session(),
                x_api_key=None,
                pullbox_session=token,
            )

        assert result is None


class TestRequireAuth:
    """Tests for require_auth dependency."""

    @pytest.mark.asyncio
    async def test_require_auth_returns_user(self) -> None:
        """Should return user when authenticated."""
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        result = await require_auth(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_require_auth_raises_when_none(self) -> None:
        """Should raise AuthenticationError when user is None."""
        from pullbox.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            await require_auth(None)


class TestRequireInteractiveAuth:
    """Tests for require_interactive_auth dependency."""

    @pytest.mark.asyncio
    async def test_session_auth_is_allowed(self) -> None:
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        request = _make_request()
        request.state.auth_method = "session"

        result = await require_interactive_auth(request, user)
        assert result is user

    @pytest.mark.asyncio
    async def test_local_bypass_is_allowed(self) -> None:
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        request = _make_request()
        request.state.auth_method = "local_bypass"

        result = await require_interactive_auth(request, user)
        assert result is user

    @pytest.mark.asyncio
    async def test_api_key_is_rejected(self) -> None:
        from pullbox.core.exceptions import AuthenticationError
        from pullbox.models.user import User

        user = MagicMock(spec=User)
        request = _make_request()
        request.state.auth_method = "api_key"

        with pytest.raises(
            AuthenticationError,
            match="Interactive operator authentication required",
        ):
            await require_interactive_auth(request, user)

    @pytest.mark.asyncio
    async def test_missing_user_is_rejected(self) -> None:
        from pullbox.core.exceptions import AuthenticationError

        request = _make_request()
        request.state.auth_method = None

        with pytest.raises(AuthenticationError):
            await require_interactive_auth(request, None)


class TestGetDbDep:
    """Tests for get_db_dep re-export."""

    @pytest.mark.asyncio
    async def test_get_db_dep_yields_session(self) -> None:
        """get_db_dep should yield a session from _get_db."""
        session = AsyncMock()

        async def _fake_get_db():  # type: ignore[no-untyped-def]
            yield session

        with patch("pullbox.api.deps._get_db", _fake_get_db):
            async for s in get_db_dep():
                assert s is session


class TestIsLocalAddressEdgeCases:
    """Edge cases for _is_local_address."""

    def test_empty_entry_skipped(self) -> None:
        """Empty entries in the comma-separated list should be skipped."""
        assert _is_local_address("192.168.1.1", ",,192.168.1.1,,") is True

    def test_invalid_entry_skipped(self) -> None:
        """Invalid entries should be skipped without error."""
        assert _is_local_address("192.168.1.1", "not-an-ip,192.168.1.1") is True

    def test_invalid_client_ip(self) -> None:
        """Invalid client IP should return False."""
        assert _is_local_address("not-an-ip", "192.168.1.0/24") is False

    def test_empty_local_addresses_returns_false(self) -> None:
        """Empty local_addresses string should return False."""
        assert _is_local_address("192.168.1.1", "") is False

    def test_no_match_returns_false(self) -> None:
        """Non-matching IP should return False."""
        assert _is_local_address("10.0.0.1", "192.168.1.0/24") is False
