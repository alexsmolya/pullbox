"""Unit tests for filesystem endpoint security — authentication and path restriction.

Tests verify that the filesystem browsing endpoint requires authentication,
blocks sensitive system directories, and sanitizes path traversal attempts.

Run:
    pytest tests/unit/test_filesystem_security.py -v
    pytest tests/unit/test_filesystem_security.py -v --cov=pullbox.api.v1.filesystem
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.api.v1.filesystem import _discover_quick_links, _validate_browsable_path
from pullbox.models import Base
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-filesystem-tests")


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
async def _test_db() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create an in-memory database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def _seed_user(_test_db: async_sessionmaker[AsyncSession]) -> None:
    """Create a test user with known credentials."""
    async with _test_db() as session:
        user = User(
            username="testuser",
            password_hash=AuthService.hash_password("testpassword"),
        )
        session.add(user)
        await session.commit()


@pytest.fixture
async def client(
    _test_db: async_sessionmaker[AsyncSession],
    _seed_user: None,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP test client with the full FastAPI app."""
    from pullbox.api.deps import get_db_dep
    from pullbox.app import create_app

    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with _test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    """Login and return cookies dict for authenticated requests."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "testpassword"},
    )
    assert resp.status_code == 200
    return dict(resp.cookies)


# ── Authentication Tests ───────────────────────────────────────────


class TestFilesystemAuthentication:
    """Tests verifying authentication is required for filesystem browsing."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/filesystem/directories",
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_request_succeeds(self, client: AsyncClient) -> None:
        cookies = await _login(client)
        resp = await client.get(
            "/api/v1/filesystem/directories",
            cookies=cookies,
            params={"path": "/"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "directories" in data
        assert "quick_links" in data


# ── Path Validation Tests (unit-level) ─────────────────────────────


class TestPathValidation:
    """Tests for the _validate_browsable_path() helper."""

    def test_path_traversal_blocked(self) -> None:
        result = _validate_browsable_path("/../../../etc/shadow")
        # Should resolve to root (safe fallback) since /etc is blocked
        assert str(result) == "/"

    def test_sensitive_directory_blocked_etc(self) -> None:
        result = _validate_browsable_path("/etc")
        assert str(result) == "/"

    def test_sensitive_directory_blocked_etc_child(self) -> None:
        result = _validate_browsable_path("/etc/ssh")
        assert str(result) == "/"

    def test_sensitive_directory_blocked_proc(self) -> None:
        result = _validate_browsable_path("/proc/self/environ")
        assert str(result) == "/"

    def test_sensitive_directory_blocked_sys(self) -> None:
        result = _validate_browsable_path("/sys")
        assert str(result) == "/"

    def test_sensitive_directory_blocked_dev(self) -> None:
        result = _validate_browsable_path("/dev")
        assert str(result) == "/"

    def test_long_path_rejected(self) -> None:
        long_path = "/" + "a" * 5000
        result = _validate_browsable_path(long_path)
        assert str(result) == "/"

    def test_null_byte_stripped(self) -> None:
        # Null bytes should be stripped; the cleaned path should still be validated
        result = _validate_browsable_path("/tmp\x00/evil")
        # After stripping null: "/tmp/evil" — doesn't exist, so falls back to "/"
        assert result == Path("/").resolve()

    def test_nonexistent_path_returns_fallback(self) -> None:
        result = _validate_browsable_path("/this/does/not/exist")
        assert str(result) == "/"

    def test_valid_path_accepted(self) -> None:
        # /tmp should exist and be allowed
        result = _validate_browsable_path("/tmp")
        assert result == Path("/tmp").resolve()

    def test_non_printable_characters_blocked(self) -> None:
        result = _validate_browsable_path("/tmp/\x01\x02test")
        assert str(result) == "/"


# ── Quick Links ────────────────────────────────────────────────────


class TestQuickLinksPreserved:
    """Verify quick_links functionality still works for authenticated users."""

    @pytest.mark.asyncio
    async def test_quick_links_preserved(self, client: AsyncClient) -> None:
        cookies = await _login(client)
        resp = await client.get(
            "/api/v1/filesystem/directories",
            cookies=cookies,
            params={"path": "/"},
        )
        assert resp.status_code == 200
        data = resp.json()
        quick_links = data["quick_links"]
        assert len(quick_links) > 0

        # Should always have at least Home and /
        labels = [ql["label"] for ql in quick_links]
        assert "Home" in labels
        assert "/" in labels


# ── Quick Links Platform Tests ────────────────────────────────────


class TestQuickLinksPlatforms:
    """Tests for _discover_quick_links() on different platforms."""

    def test_linux_quick_links(self, tmp_path: Path) -> None:
        mnt = tmp_path / "mnt"
        mnt.mkdir()
        share = mnt / "nas"
        share.mkdir()

        media = tmp_path / "media"
        media.mkdir()
        usb = media / "usb"
        usb.mkdir()
        hidden = media / ".hidden"
        hidden.mkdir()

        with (
            patch("pullbox.api.v1.filesystem.platform.system", return_value="Linux"),
            patch("pullbox.api.v1.filesystem.Path.home", return_value=tmp_path),
            patch(
                "pullbox.api.v1.filesystem._discover_quick_links",
                wraps=_discover_quick_links,
            ),
        ):
            # Patch individual path checks to point at tmp_path children
            original_is_dir = Path.is_dir

            def _fake_is_dir(self: Path) -> bool:
                s = str(self)
                if s == "/mnt":
                    return True
                if s == "/media":
                    return True
                return original_is_dir(self)

            original_iterdir = Path.iterdir

            def _fake_iterdir(self: Path) -> list[Path]:
                s = str(self)
                if s == "/mnt":
                    return original_iterdir(mnt)
                if s == "/media":
                    return original_iterdir(media)
                return original_iterdir(self)

            with (
                patch.object(Path, "is_dir", _fake_is_dir),
                patch.object(Path, "iterdir", _fake_iterdir),
            ):
                links = _discover_quick_links()

        labels = [ql.label for ql in links]
        assert "Mounts" in labels
        assert "Media" in labels
        assert "nas" in labels
        assert "usb" in labels
        assert ".hidden" not in labels

    def test_windows_quick_links(self) -> None:
        with (
            patch("pullbox.api.v1.filesystem.platform.system", return_value="Windows"),
            patch("pullbox.api.v1.filesystem.Path.home", return_value=Path("C:\\Users\\test")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            links = _discover_quick_links()

        labels = [ql.label for ql in links]
        # Should include drive letters C: through Z:
        assert "C:" in labels
        assert "D:" in labels


# ── PermissionError Handling ──────────────────────────────────────


class TestPermissionErrorHandling:
    """Tests for PermissionError handling in list_directories."""

    @pytest.mark.asyncio
    async def test_permission_denied_returns_empty_dirs(self, client: AsyncClient) -> None:
        cookies = await _login(client)

        with patch("pullbox.api.v1.filesystem.Path.iterdir", side_effect=PermissionError):
            resp = await client.get(
                "/api/v1/filesystem/directories",
                cookies=cookies,
                params={"path": "/"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["directories"] == []
