"""Route-contract tests for the first-run setup shell."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-setup-ui")


@pytest.mark.asyncio
class TestSetupWizardRouteContracts:
    """Verify first-run setup stays a lean single-page account flow."""

    async def test_setup_wizard_uses_lean_first_run_assets(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/setup")

        assert response.status_code == 200
        assert 'data-testid="setup-page"' in response.text
        assert 'data-testid="setup-shell"' in response.text
        assert 'data-testid="setup-card"' in response.text
        assert 'id="setup-critical-shell"' in response.text
        assert 'rel="preload" href="/static/css/tailwind.css?v=' not in response.text
        assert 'rel="stylesheet"' not in response.text
        assert "/static/js/alpine.min.js?v=" not in response.text
        assert "/static/js/pullbox.js?v=" not in response.text
        assert "/static/css/pullbox.css" not in response.text
        assert "/static/js/tailwind.js" not in response.text
        assert 'rel="preload" href="/static/fonts/' not in response.text
        assert 'data-standalone-shell-version="' in response.text
        assert "__pbValidateStandaloneShellFreshness" not in response.text
        assert "preventStandaloneDocumentRestore" not in response.text
        assert 'x-data="setupWizard()"' not in response.text

    async def test_setup_wizard_matches_single_page_account_shell(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/setup")

        assert response.status_code == 200
        assert "Create your first account." in response.text
        assert "ACCOUNT SETUP" in response.text
        assert "Create your account" in response.text
        assert 'data-testid="setup-step-picker"' not in response.text
        assert 'data-testid="setup-side-steps"' not in response.text
        assert 'class="setup-step-list"' not in response.text
        assert "Step 1 of 6" not in response.text
        assert "Library root" not in response.text
        assert "ComicVine" not in response.text
        assert "Download client" not in response.text
        assert "Search sources" not in response.text
        assert "Optional" not in response.text
        assert "Configured Now" not in response.text
        assert 'data-testid="setup-hero-block"' in response.text
        assert 'class="setup-hero-headline"' in response.text
        assert 'class="setup-kicker">ACCOUNT SETUP</p>' in response.text
        assert 'class="setup-card-title">Create your account</h1>' in response.text
        assert (
            "Once your account is saved, you'll head straight to the sign-in page." in response.text
        )
        assert "This locks down access before anything else gets configured." not in response.text
        assert "Choose your library root" not in response.text
        assert "Connect ComicVine" not in response.text
        assert "Pullbox is ready" not in response.text
        assert 'x-show="step === 1"' not in response.text
        assert 'x-show="step === 2"' not in response.text
        assert 'x-show="step === 3"' not in response.text
        assert 'x-show="step === 4"' not in response.text
        assert 'x-show="step === 5"' not in response.text
        assert 'data-testid="setup-boot-splash"' not in response.text
        assert '<body class="setup-shell-body"' in response.text
        assert 'data-testid="setup-page"' in response.text
        assert 'data-testid="setup-account-form"' in response.text
        assert 'data-testid="setup-side-panel"' in response.text
        assert "Instance online" in response.text
        assert "data-shell-pending" not in response.text

    async def test_setup_wizard_reuses_app_sidebar_brand_contract(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/setup")

        assert response.status_code == 200
        assert 'class="setup-brand"' in response.text
        assert 'class="setup-brand-wordmark"' in response.text
        assert 'aria-label="Pullbox"' in response.text
        assert "v{{ version }}" not in response.text

    async def test_setup_wizard_uses_inline_system_font_shell_styles(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/setup")

        assert response.status_code == 200
        assert "font-family: var(--setup-sans);" in response.text
        assert "--setup-sans: ui-sans-serif, system-ui" in response.text
        assert ".setup-hero-headline {" in response.text
        assert "font-size: 1.5rem;" in response.text
        assert ".setup-step-list {" not in response.text
        assert ".setup-card-title {" in response.text

    async def test_setup_redirects_to_login_when_first_account_exists(
        self,
        unauthenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        from pullbox.models.user import User
        from pullbox.services.auth_service import AuthService

        async with sec_db() as session:
            session.add(
                User(
                    username="admin",
                    password_hash=AuthService.hash_password("Password@1"),
                )
            )
            await session.commit()

        response = await unauthenticated_client.get("/setup", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    async def test_setup_skips_back_to_login_when_first_account_exists(
        self,
        unauthenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        from pullbox.models.user import User
        from pullbox.services.auth_service import AuthService

        async with sec_db() as session:
            session.add(
                User(
                    username="admin",
                    password_hash=AuthService.hash_password("Password@1"),
                )
            )
            await session.commit()

        response = await unauthenticated_client.get("/setup", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/login"
