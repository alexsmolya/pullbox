"""Focused API coverage for the shared filesystem browser."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.config import SystemConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-filesystem")


@pytest.fixture
async def _db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def _session_token(_db_factory: async_sessionmaker[AsyncSession]) -> str:
    async with _db_factory() as session:
        from pullbox.models.user import User

        user = User(
            username="filesystemuser",
            password_hash=AuthService.hash_password("Test@1234"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return AuthService.create_session_token(user.id, user.session_version)


@pytest.fixture
async def client(_db_factory: async_sessionmaker[AsyncSession], _session_token: str):
    from pullbox.api.deps import get_db_dep
    from pullbox.api.middleware import reset_setup_cache
    from pullbox.app import create_app

    app = create_app()

    async def _override_db():
        async with _db_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db
    reset_setup_cache()

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={SESSION_COOKIE_NAME: _session_token},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    reset_setup_cache()


@pytest.mark.asyncio
async def test_browse_uses_configured_allowed_extensions_by_default(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    """When no extensions override is provided, browse uses the configured import allowlist."""
    (tmp_path / "comic.cbz").write_text("zip")
    (tmp_path / "guide.pdf").write_text("pdf")
    (tmp_path / "notes.txt").write_text("text")
    (tmp_path / "subdir").mkdir()

    async with _db_factory() as session:
        session.add(
            SystemConfig(
                key="allowed_import_extensions",
                value=".pdf",
                value_type="string",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/filesystem/browse", params={"path": str(tmp_path)})

    assert resp.status_code == 200
    data = resp.json()
    assert [entry["name"] for entry in data["files"]] == ["guide.pdf"]
    assert [entry["name"] for entry in data["directories"]] == ["subdir"]


@pytest.mark.asyncio
async def test_browse_explicit_extensions_override_configured_default(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    """A browser-specific extensions override wins over the configured default list."""
    (tmp_path / "comic.cbz").write_text("zip")
    (tmp_path / "guide.pdf").write_text("pdf")

    async with _db_factory() as session:
        session.add(
            SystemConfig(
                key="allowed_import_extensions",
                value=".pdf",
                value_type="string",
            )
        )
        await session.commit()

    resp = await client.get(
        "/api/v1/filesystem/browse",
        params={"path": str(tmp_path), "extensions": "cbz"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert [entry["name"] for entry in data["files"]] == ["comic.cbz"]


@pytest.mark.asyncio
async def test_browse_clamps_navigation_to_allowed_roots(
    client: AsyncClient,
    tmp_path,
) -> None:
    """Constrained roots should pin the browser inside the allowed subtree."""
    allowed_root = tmp_path / "library"
    disallowed_root = tmp_path / "outside"
    allowed_root.mkdir()
    disallowed_root.mkdir()
    (allowed_root / "batman.cbz").write_text("zip")
    (disallowed_root / "other.cbz").write_text("zip")

    resp = await client.get(
        "/api/v1/filesystem/browse",
        params={"path": str(disallowed_root), "roots": str(allowed_root)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == str(allowed_root)
    assert data["parent"] is None
    assert [entry["path"] for entry in data["quick_links"]] == [str(allowed_root)]


@pytest.mark.asyncio
async def test_browse_with_only_invalid_allowed_roots_fails_closed(
    client: AsyncClient,
    tmp_path,
) -> None:
    """Supplying only invalid constrained roots should not expand to unrestricted browsing."""
    allowed_root = tmp_path / "missing-library-root"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    (outside_root / "other.cbz").write_text("zip")

    resp = await client.get(
        "/api/v1/filesystem/browse",
        params={"path": str(outside_root), "roots": str(allowed_root)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "/"
    assert data["parent"] is None
    assert data["directories"] == []
    assert data["files"] == []
    assert data["quick_links"] == []


@pytest.mark.asyncio
async def test_directories_with_only_invalid_allowed_roots_fails_closed(
    client: AsyncClient,
    tmp_path,
) -> None:
    """Directory-only constrained browsing should also fail closed when all roots are invalid."""
    allowed_root = tmp_path / "missing-library-root"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    (outside_root / "subdir").mkdir()

    resp = await client.get(
        "/api/v1/filesystem/directories",
        params={"path": str(outside_root), "roots": str(allowed_root)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "/"
    assert data["parent"] is None
    assert data["directories"] == []
    assert data["quick_links"] == []
