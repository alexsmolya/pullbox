"""Setup page object for the first-run account-creation shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SetupWizardPage(BasePage):
    """Page object for the /setup first-run account shell."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        """Navigate to the setup page."""
        self.navigate("/setup")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='setup-page']").first

    @property
    def shell(self) -> Locator:
        return self.page.locator("[data-testid='setup-shell']").first

    @property
    def card(self) -> Locator:
        return self.page.locator("[data-testid='setup-card']").first

    def fill_username(self, username: str) -> None:
        """Fill the username field."""
        self.page.locator("#setup-account-username").fill(username)

    def fill_password(self, password: str) -> None:
        """Fill the password field."""
        self.page.locator("#setup-account-password").fill(password)

    def fill_confirm_password(self, password: str) -> None:
        """Fill the confirm password field."""
        self.page.locator("#setup-account-password-confirm").fill(password)

    def submit_account(self) -> None:
        """Click the Create Account button."""
        self.page.get_by_role("button", name="Create Account").click()

    def is_account_error_visible(self) -> bool:
        """Check if an account creation error message is displayed."""
        error = self.page.locator("[x-show='error']").first
        return error.is_visible() if error.count() > 0 else False
