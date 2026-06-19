"""Route-contract tests for the rewritten security shell."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-security-ui")


@pytest.mark.asyncio
class TestSecurityRouteContracts:
    """Verify the security area renders a stable mounted shell."""

    async def test_security_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/security")

        assert response.status_code == 200
        assert 'data-testid="security-page"' in response.text
        assert 'data-admin-workspace-contract="v1"' in response.text
        assert 'data-testid="security-header"' in response.text
        assert 'data-admin-workspace-header="v1"' in response.text
        assert 'data-testid="security-page-title"' in response.text
        assert ">SECU<span>RITY</span><" in response.text
        assert 'data-testid="security-page-subtitle"' in response.text
        assert 'class="series-registry-title"' in response.text
        assert 'class="series-registry-subtitle"' in response.text
        assert 'data-testid="security-body"' in response.text
        assert 'data-testid="security-tabs"' in response.text
        assert 'data-admin-workspace-rail="v1"' in response.text
        assert 'data-testid="security-content"' in response.text
        assert 'data-testid="page-footer-dock"' in response.text
        assert 'data-testid="security-footer-dock"' in response.text
        assert 'data-testid="security-tab-authentication"' in response.text
        assert 'data-testid="security-panel-authentication"' in response.text
        assert 'data-testid="security-authentication-access-model-card"' in response.text
        assert 'data-testid="security-authentication-account-identity-card"' in response.text
        assert 'data-testid="security-authentication-password-security-card"' in response.text
        assert 'data-testid="security-authentication-username-form"' in response.text
        assert 'data-testid="security-authentication-password-form"' in response.text
        assert "Bypass Account" in response.text
        assert "full operator access without login" in response.text
        assert "Current request appears as" in response.text
        assert 'data-testid="security-current-client-ip"' in response.text

    async def test_security_htmx_tab_returns_content_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/htmx/security/file_safety",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'id="page-footer-dock"' in response.text
        assert 'hx-swap-oob="innerHTML"' in response.text
        assert 'data-testid="security-footer-dock"' in response.text
        assert 'data-testid="security-content"' in response.text
        assert 'data-testid="security-panel-file_safety"' in response.text
        assert 'data-testid="security-body"' not in response.text
        assert 'data-testid="security-tabs"' not in response.text
        assert 'data-testid="security-page"' not in response.text
        assert 'data-testid="page-dock-status"' not in response.text

    async def test_security_audit_log_uses_shared_local_dropdown(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/security?tab=audit_log")

        assert response.status_code == 200
        assert 'data-testid="security-panel-audit_log"' in response.text
        assert 'data-testid="security-audit-log-events-card"' in response.text
        assert 'data-testid="security-audit-type-select"' in response.text
        assert 'data-dropdown-select-contract="v1"' in response.text
        assert 'data-dropdown-select-mode="local"' in response.text
        assert "selectedType" in response.text
        assert 'data-testid="page-dock-status"' in response.text

    async def test_security_audit_log_uses_shared_table_contract_and_safe_event_badges(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/security?tab=audit_log")

        assert response.status_code == 200
        assert 'data-testid="security-audit-table"' in response.text
        assert 'data-testid="security-audit-log-events-card"' in response.text
        assert 'class="section-card overflow-visible"' in response.text
        assert 'class="downloads-table-wrap"' in response.text
        assert 'class="downloads-table min-w-[760px]"' in response.text
        assert ":class=\"eventBadgeClass(event.event_type) || 'pill-neutral'\"" in response.text
        assert "config_changed" in response.text
        assert 'security_config_changed: "pill-info"' in response.text
        assert "session_invalidated_version_mismatch" in response.text
        assert "session_invalidated_user_inactive" in response.text
        assert "pill-neutral" in response.text
        assert "matching events" not in response.text

    async def test_security_file_safety_renders_server_backed_dangerous_toggle_state(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/security?tab=file_safety")

        assert response.status_code == 200
        assert 'data-testid="security-file-safety-dangerous-toggle"' in response.text
        assert 'x-model="blockDangerous"' in response.text
        assert "checked" in response.text
        assert ">Enabled</span>" in response.text

    async def test_security_api_access_uses_shared_downloads_table_and_action_contract(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/security?tab=api_access")

        assert response.status_code == 200
        assert 'data-testid="security-api-access-registry-card"' in response.text
        assert 'data-testid="security-api-access-table"' in response.text
        assert 'class="downloads-table-wrap"' in response.text
        assert 'class="downloads-table"' in response.text
        assert 'class="downloads-action-btn is-danger"' in response.text
        assert 'data-testid="security-api-access-revoke-btn"' in response.text
        assert "active keys" not in response.text
        assert "expiring soon" not in response.text
        assert "unused" not in response.text
