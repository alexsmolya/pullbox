"""Integration tests for audit log wiring in auth routes.

Verifies that security events are recorded in the audit log when
authentication-related actions occur through the API.

Run:
    pytest tests/integration/test_audit_integration.py -v
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient

    from pullbox.models.user import User

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-audit-tests")

pytest_plugins = ["conftest_security"]

AUDIT_URL = "/api/v1/audit/events"
LOGIN_URL = "/api/v1/auth/login"
ACCOUNT_URL = "/api/v1/auth/account"
APIKEYS_URL = "/api/v1/auth/apikeys"


async def _get_csrf(client: AsyncClient) -> str:
    """Extract CSRF token from the authenticated client's session cookie."""
    from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

    token = client.cookies.get(SESSION_COOKIE_NAME, "")
    return AuthService.get_csrf_token_from_session(token) or ""


@pytest.mark.asyncio
class TestAuditLoginIntegration:
    """Tests that login events create audit log entries."""

    async def test_login_success_creates_audit_entry(
        self,
        unauthenticated_client: AsyncClient,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Successful login creates a LOGIN_SUCCESS audit entry."""
        await unauthenticated_client.post(
            LOGIN_URL, json={"username": "testuser", "password": "Test@1234"}
        )

        resp = await authenticated_client.get(AUDIT_URL, params={"event_type": "login_success"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        entry = data["events"][0]
        assert entry["event_type"] == "login_success"
        assert entry["username"] == "testuser"

    async def test_login_failure_calls_audit(
        self,
        unauthenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Failed login calls audit with LOGIN_FAILURE event type.

        Note: The db session rolls back on AuthenticationError, so the
        audit entry is not persisted. We verify the call was made.
        """
        from pullbox.models.audit_log import AuditEventType

        original = AsyncMock(wraps=None)
        with patch("pullbox.services.audit_service.AuditService.log_event", original) as mock_log:
            await unauthenticated_client.post(
                LOGIN_URL,
                json={"username": "testuser", "password": "WrongPassword1!"},
            )
            # Verify audit was called with LOGIN_FAILURE
            calls = [c for c in mock_log.call_args_list if c[0][1] == AuditEventType.LOGIN_FAILURE]
            assert len(calls) >= 1
            assert calls[0].kwargs.get("username") == "testuser"


@pytest.mark.asyncio
class TestAuditAccountIntegration:
    """Tests that account changes create audit log entries."""

    async def test_password_change_creates_audit_entry(
        self,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Password change calls audit with PASSWORD_CHANGED event.

        Note: Password changes bump the session version, invalidating
        the current session token. We verify the audit call via mock.
        """
        from pullbox.models.audit_log import AuditEventType
        from pullbox.services.audit_service import AuditService

        original_log = AuditService.log_event
        calls: list[tuple[object, ...]] = []

        async def _tracking_log(
            session: object,
            event_type: AuditEventType,
            **kwargs: object,
        ) -> object:
            calls.append((event_type, kwargs))
            return await original_log(session, event_type, **kwargs)  # type: ignore[arg-type]

        csrf = await _get_csrf(authenticated_client)

        with patch(
            "pullbox.services.audit_service.AuditService.log_event",
            side_effect=_tracking_log,
        ):
            resp = await authenticated_client.put(
                ACCOUNT_URL,
                json={
                    "current_password": "Test@1234",
                    "new_password": "NewTest@5678",
                    "confirm_password": "NewTest@5678",
                },
                headers={"X-CSRF-Token": csrf},
            )
        assert resp.status_code == 200

        pw_calls = [c for c in calls if c[0] == AuditEventType.PASSWORD_CHANGED]
        assert len(pw_calls) >= 1
        assert pw_calls[0][1].get("source_ip")


@pytest.mark.asyncio
class TestAuditApiKeyIntegration:
    """Tests that API key operations create audit log entries."""

    async def test_api_key_create_creates_audit_entry(
        self,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Creating an API key creates an API_KEY_CREATED audit entry."""
        csrf = await _get_csrf(authenticated_client)

        resp = await authenticated_client.post(
            APIKEYS_URL,
            json={"name": "test-audit-key"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201

        # Verify the key value is NOT in the audit log detail
        audit_resp = await authenticated_client.get(
            AUDIT_URL, params={"event_type": "api_key_created"}
        )
        data = audit_resp.json()
        assert data["total"] >= 1
        entry = data["events"][0]
        assert entry["event_type"] == "api_key_created"
        assert entry["source_ip"]
        assert "test-audit-key" in (entry["detail"] or "")
        # Raw key should never appear in audit detail
        raw_key = resp.json().get("key", "")
        if raw_key and entry["detail"]:
            assert raw_key not in entry["detail"]

    async def test_api_key_revoke_creates_audit_entry(
        self,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Revoking an API key creates an API_KEY_REVOKED audit entry."""
        csrf = await _get_csrf(authenticated_client)

        # Create a key first
        create_resp = await authenticated_client.post(
            APIKEYS_URL,
            json={"name": "revoke-me"},
            headers={"X-CSRF-Token": csrf},
        )
        assert create_resp.status_code == 201
        key_id = create_resp.json()["api_key"]["id"]

        # Revoke it
        resp = await authenticated_client.delete(
            f"{APIKEYS_URL}/{key_id}",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 204

        audit_resp = await authenticated_client.get(
            AUDIT_URL, params={"event_type": "api_key_revoked"}
        )
        data = audit_resp.json()
        assert data["total"] >= 1
        assert data["events"][0]["event_type"] == "api_key_revoked"
        assert data["events"][0]["source_ip"]
        assert "revoke-me" in (data["events"][0]["detail"] or "")


@pytest.mark.asyncio
class TestAuditConfigIntegration:
    """Tests that security-sensitive config changes create audit log entries."""

    async def test_security_config_change_creates_audit_entry_with_source_ip(
        self,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Changing security config emits a queryable audit event."""
        csrf = await _get_csrf(authenticated_client)

        resp = await authenticated_client.put(
            "/api/v1/config",
            json={"values": {"session_lifetime_hours": "48"}},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        audit_resp = await authenticated_client.get(
            AUDIT_URL, params={"event_type": "security_config_changed"}
        )
        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["total"] >= 1
        entry = data["events"][0]
        assert entry["event_type"] == "security_config_changed"
        assert entry["user_id"] == sec_user.id
        assert entry["username"] == sec_user.username
        assert entry["source_ip"]
        assert "session_lifetime_hours" in (entry["detail"] or "")

    async def test_local_bypass_toggle_creates_specific_audit_entry_with_source_ip(
        self,
        authenticated_client: AsyncClient,
        sec_user: User,
    ) -> None:
        """Enabling local auth bypass emits the dedicated toggle event."""
        csrf = await _get_csrf(authenticated_client)

        resp = await authenticated_client.put(
            "/api/v1/config",
            json={
                "values": {
                    "local_auth_bypass_enabled": "true",
                    "local_auth_bypass_addresses": "127.0.0.1",
                    "local_auth_bypass_username": sec_user.username,
                }
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        audit_resp = await authenticated_client.get(
            AUDIT_URL, params={"event_type": "local_bypass_toggled"}
        )
        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["total"] >= 1
        entry = data["events"][0]
        assert entry["event_type"] == "local_bypass_toggled"
        assert entry["user_id"] == sec_user.id
        assert entry["username"] == sec_user.username
        assert entry["source_ip"]
        assert "enabled" in (entry["detail"] or "")


@pytest.mark.asyncio
class TestAuditBestEffort:
    """Tests that audit logging failures don't break primary operations."""

    async def test_audit_failure_does_not_break_login(
        self, unauthenticated_client: AsyncClient, sec_user: User
    ) -> None:
        """If audit logging raises, login still succeeds."""
        mock = AsyncMock(side_effect=RuntimeError("DB write failed"))
        with patch("pullbox.services.audit_service.AuditService.log_event", mock):
            resp = await unauthenticated_client.post(
                LOGIN_URL, json={"username": "testuser", "password": "Test@1234"}
            )
        assert resp.status_code == 200
        assert "csrf_token" in resp.json()
