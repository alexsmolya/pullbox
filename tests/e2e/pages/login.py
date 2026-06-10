"""Login page object — encapsulates the /login form interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class LoginPage(BasePage):
    """Page object for the /login page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        """Navigate to the login page."""
        self.navigate("/login")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='login-page']").first

    @property
    def card(self) -> Locator:
        return self.page.locator("[data-testid='login-card']").first

    @property
    def hero(self) -> Locator:
        return self.page.locator("[data-testid='login-hero']").first

    @property
    def desktop_brand(self) -> Locator:
        return self.page.locator("[data-testid='login-brand-desktop']").first

    @property
    def form(self) -> Locator:
        return self.page.locator("[data-testid='login-form']").first

    @property
    def username_input(self) -> Locator:
        return self.page.locator("[data-testid='login-username']").first

    @property
    def password_input(self) -> Locator:
        return self.page.locator("[data-testid='login-password']").first

    @property
    def submit_button(self) -> Locator:
        return self.page.locator("[data-testid='login-submit']").first

    @property
    def error_banner(self) -> Locator:
        return self.page.locator("[data-testid='login-error']").first

    def fill_username(self, username: str) -> None:
        """Fill the username field."""
        self.username_input.fill(username)

    def fill_password(self, password: str) -> None:
        """Fill the password field."""
        self.password_input.fill(password)

    def submit(self) -> None:
        """Click the sign-in button."""
        self.submit_button.click()

    def get_error_message(self) -> str | None:
        """Return the login error message text, or None if not visible."""
        if self.error_banner.is_visible():
            return self.error_banner.text_content()
        return None

    def login(self, username: str, password: str) -> None:
        """Convenience: fill both fields and submit."""
        self.goto()
        self.fill_username(username)
        self.fill_password(password)
        self.submit()
