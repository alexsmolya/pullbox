"""Tests for the GET /api/v1/auth/password-policy endpoint.

Verifies that the password policy endpoint returns the correct structure,
requires no authentication, and stays in sync with the password_policy module.

Run:
    pytest tests/api/test_password_policy_endpoint.py -v
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

# Ensure conftest_security fixtures are available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-policy-tests")

pytest_plugins = ["conftest_security"]

POLICY_URL = "/api/v1/auth/password-policy"

EXPECTED_REQUIREMENT_IDS = {
    "min_length",
    "max_length",
    "max_bytes",
    "uppercase",
    "lowercase",
    "digit",
    "special",
}


@pytest.mark.asyncio
class TestPasswordPolicyEndpoint:
    """Tests for the password policy API endpoint."""

    async def test_get_password_policy_returns_requirements(
        self, authenticated_client: AsyncClient
    ) -> None:
        """GET /api/v1/auth/password-policy returns 200 with policy data."""
        resp = await authenticated_client.get(POLICY_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert "min_length" in data
        assert "max_length" in data
        assert "max_bytes" in data
        assert "requirements" in data
        assert isinstance(data["requirements"], list)

    async def test_password_policy_no_auth_required(
        self, unauthenticated_client: AsyncClient
    ) -> None:
        """Endpoint is public — no session cookie needed."""
        resp = await unauthenticated_client.get(POLICY_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert "min_length" in data

    async def test_policy_min_length_matches_module(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Response min_length matches the password_policy module constant."""
        from pullbox.core.password_policy import MIN_PASSWORD_LENGTH

        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        assert data["min_length"] == MIN_PASSWORD_LENGTH

    async def test_policy_max_length_matches_module(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Response max_length matches the password_policy module constant."""
        from pullbox.core.password_policy import MAX_PASSWORD_LENGTH

        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        assert data["max_length"] == MAX_PASSWORD_LENGTH

    async def test_policy_max_bytes_matches_module(self, authenticated_client: AsyncClient) -> None:
        """Response max_bytes matches the password_policy module constant."""
        from pullbox.core.password_policy import MAX_PASSWORD_BYTES

        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        assert data["max_bytes"] == MAX_PASSWORD_BYTES

    async def test_policy_requirements_count(self, authenticated_client: AsyncClient) -> None:
        """Response has exactly 7 requirements."""
        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        assert len(data["requirements"]) == 7

    async def test_policy_requirement_ids(self, authenticated_client: AsyncClient) -> None:
        """All expected requirement IDs are present."""
        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        ids = {r["id"] for r in data["requirements"]}
        assert ids == EXPECTED_REQUIREMENT_IDS

    async def test_requirements_have_label_and_type(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Each requirement has id, label, and type fields."""
        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        for req in data["requirements"]:
            assert "id" in req
            assert "label" in req
            assert "type" in req
            assert isinstance(req["label"], str)
            assert req["type"] in ("length", "character")

    async def test_length_requirements_typed_correctly(
        self, authenticated_client: AsyncClient
    ) -> None:
        """min_length and max_length requirements have type 'length'."""
        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        by_id = {r["id"]: r for r in data["requirements"]}
        assert by_id["min_length"]["type"] == "length"
        assert by_id["max_length"]["type"] == "length"
        assert by_id["max_bytes"]["type"] == "length"

    async def test_character_requirements_typed_correctly(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Character class requirements have type 'character'."""
        resp = await authenticated_client.get(POLICY_URL)
        data = resp.json()
        by_id = {r["id"]: r for r in data["requirements"]}
        for req_id in ("uppercase", "lowercase", "digit", "special"):
            assert by_id[req_id]["type"] == "character"
