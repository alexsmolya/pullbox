"""Focused API coverage for first-run setup."""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import select

from pullbox.models.user import User
from pullbox.services.auth_service import SESSION_COOKIE_NAME

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-setup-api")


@pytest.mark.asyncio
async def test_setup_creates_first_user_and_requires_login(
    unauthenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    response = await unauthenticated_client.post(
        "/api/v1/system/setup",
        json={"username": "admin", "password": "Password@1"},
    )

    assert response.status_code == 201
    assert response.json() == {"message": "Account created. Please log in."}
    assert SESSION_COOKIE_NAME not in response.cookies
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")

    async with sec_db() as session:
        user_result = await session.execute(select(User).where(User.username == "admin"))

    assert user_result.scalar_one().username == "admin"


@pytest.mark.asyncio
async def test_setup_rejects_when_first_account_already_exists(
    unauthenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.services.auth_service import AuthService

    async with sec_db() as session:
        session.add(
            User(
                username="admin",
                password_hash=AuthService.hash_password("Password@1"),
            )
        )
        await session.commit()

    response = await unauthenticated_client.post(
        "/api/v1/system/setup",
        json={"username": "admin2", "password": "Password@1"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Setup has already been completed."
