"""Integration tests for API exposure hardening decisions."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from pullbox.core.local_auth_bypass import build_local_bypass_csrf_token
from pullbox.models.config import SystemConfig

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-api-exposure")


@pytest.mark.asyncio
class TestApiExposureHardening:
    """Representative auth and exposure checks for the hardened API surface."""

    async def test_api_key_still_works_for_automation_safe_route(
        self,
        unauthenticated_client: AsyncClient,
        sec_api_key: str,
    ) -> None:
        response = await unauthenticated_client.get(
            "/api/v1/series",
            headers={"X-Api-Key": sec_api_key},
        )
        assert response.status_code == 200

    async def test_api_key_rejected_for_operator_backup_route(
        self,
        unauthenticated_client: AsyncClient,
        sec_api_key: str,
    ) -> None:
        response = await unauthenticated_client.post(
            "/api/v1/system/backup",
            headers={"X-Api-Key": sec_api_key},
        )
        assert response.status_code == 401

    async def test_api_key_rejected_for_operator_utilities_route(
        self,
        unauthenticated_client: AsyncClient,
        sec_api_key: str,
    ) -> None:
        response = await unauthenticated_client.get(
            "/api/v1/utilities/jobs",
            headers={"X-Api-Key": sec_api_key},
        )
        assert response.status_code == 401

    async def test_session_auth_still_works_for_operator_route(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        response = await authenticated_client.get("/api/v1/system/about")
        assert response.status_code == 200

    async def test_local_bypass_still_works_for_operator_route(
        self,
        sec_app: object,
        sec_db,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            session.add_all(
                [
                    SystemConfig(
                        key="local_auth_bypass_enabled",
                        value="true",
                        value_type="bool",
                    ),
                    SystemConfig(
                        key="local_auth_bypass_addresses",
                        value="127.0.0.1",
                        value_type="string",
                    ),
                ]
            )
            await session.commit()

        transport = ASGITransport(app=sec_app, client=("127.0.0.1", 12345))  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/config")

        assert response.status_code == 200

    async def test_local_bypass_write_requires_csrf_token(
        self,
        sec_app: object,
        sec_db,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            session.add_all(
                [
                    SystemConfig(
                        key="local_auth_bypass_enabled",
                        value="true",
                        value_type="bool",
                    ),
                    SystemConfig(
                        key="local_auth_bypass_addresses",
                        value="127.0.0.1",
                        value_type="string",
                    ),
                    SystemConfig(
                        key="local_auth_bypass_username",
                        value=sec_user.username,
                        value_type="string",
                    ),
                ]
            )
            await session.commit()

        transport = ASGITransport(app=sec_app, client=("127.0.0.1", 12345))  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.put(
                "/api/v1/config",
                json={"values": {"session_lifetime_hours": "25"}},
            )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_ERROR"

    async def test_local_bypass_write_accepts_valid_csrf_token(
        self,
        sec_app: object,
        sec_db,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            session.add_all(
                [
                    SystemConfig(
                        key="local_auth_bypass_enabled",
                        value="true",
                        value_type="bool",
                    ),
                    SystemConfig(
                        key="local_auth_bypass_addresses",
                        value="127.0.0.1",
                        value_type="string",
                    ),
                    SystemConfig(
                        key="local_auth_bypass_username",
                        value=sec_user.username,
                        value_type="string",
                    ),
                ]
            )
            await session.commit()

        transport = ASGITransport(app=sec_app, client=("127.0.0.1", 12345))  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.put(
                "/api/v1/config",
                headers={
                    "X-CSRF-Token": build_local_bypass_csrf_token("127.0.0.1", sec_user.username)
                },
                json={"values": {"session_lifetime_hours": "25"}},
            )

        assert response.status_code == 200

    async def test_docs_and_schema_remain_public(
        self,
        unauthenticated_client: AsyncClient,
    ) -> None:
        docs_response = await unauthenticated_client.get("/docs")
        schema_response = await unauthenticated_client.get("/openapi.json")

        assert docs_response.status_code == 200
        assert schema_response.status_code == 200
        assert "paths" in schema_response.json()


@pytest.fixture
async def covers_app(
    monkeypatch: pytest.MonkeyPatch,
    sec_db,
    tmp_path: Path,
):
    """App fixture with a temp public covers directory mounted."""
    from pullbox.api.deps import get_db_dep
    from pullbox.api.middleware import reset_setup_cache
    from pullbox.app import create_app
    from pullbox.config import get_settings

    covers_dir = tmp_path / "covers"
    series_dir = covers_dir / "1"
    series_dir.mkdir(parents=True)
    (series_dir / "series.jpg").write_bytes(b"fake-jpeg")

    monkeypatch.setenv("PULLBOX_COVERS_DIR", str(covers_dir))
    get_settings.cache_clear()

    app = create_app()

    async def _override_db():
        async with sec_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db
    reset_setup_cache()

    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        reset_setup_cache()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_public_cover_assets_remain_available(covers_app: object) -> None:
    transport = ASGITransport(app=covers_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/covers/1/series.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
