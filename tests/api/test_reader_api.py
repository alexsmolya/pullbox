"""Reader manifest and revisioned page delivery API contract tests."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService
from pullbox.services.reader_content_service import ReaderContentService

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["tests.conftest_security"]


def _write_cbz(path: Path) -> None:
    page_one = io.BytesIO()
    page_two = io.BytesIO()
    with Image.new("P", (1, 1), color=0) as image:
        image.save(page_one, format="GIF")
    with Image.new("P", (1, 1), color=1) as image:
        image.save(page_two, format="GIF")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("001.gif", page_one.getvalue() + b"-page-one")
        archive.writestr("002.gif", page_two.getvalue() + b"-page-two")


async def _seed_reader_issue(
    factory: async_sessionmaker[AsyncSession],
    source: Path,
) -> int:
    async with factory() as session:
        series = Series(
            comicvine_id=800_001,
            title="Reader API Series",
            sort_title="reader api series",
            year_start=2026,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add(series)
        await session.flush()
        issue = Issue(
            series_id=series.id,
            comicvine_id=800_002,
            issue_number=1,
            title="Reader API Issue",
            status=IssueStatus.OWNED,
        )
        session.add(issue)
        await session.flush()
        root = LibraryRoot(name="reader-api", path=str(source.parent))
        session.add(root)
        await session.flush()
        stat = source.stat()
        session.add(
            LibraryFile(
                file_path=str(source),
                file_name=source.name,
                file_size=stat.st_size,
                file_format=FileFormat.CBZ,
                file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                issue_id=issue.id,
                match_confidence=MatchConfidence.HIGH,
                library_root_id=root.id,
            )
        )
        await session.commit()
        return issue.id


@pytest.mark.asyncio
async def test_manifest_and_page_are_private_authenticated_resources(
    authenticated_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
    sec_app: object,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.cbz"
    _write_cbz(source)
    issue_id = await _seed_reader_issue(sec_db, source)
    sec_app.state.reader_content_service = ReaderContentService(cache_dir=tmp_path / "cache")

    denied = await unauthenticated_client.get(f"/api/v1/reader/issues/{issue_id}/manifest")
    manifest_response = await authenticated_client.get(f"/api/v1/reader/issues/{issue_id}/manifest")

    assert denied.status_code == 401
    assert manifest_response.status_code == 200
    assert manifest_response.headers["cache-control"] == (
        "no-store, no-cache, max-age=0, must-revalidate"
    )
    manifest = manifest_response.json()
    assert manifest["page_count"] == 2
    assert manifest["initial_page_index"] == 0
    assert manifest["page_url_template"].endswith(
        "/pages/{page_index}?revision=" + manifest["revision"]
    )

    page_response = await authenticated_client.get(
        manifest["page_url_template"].replace("{page_index}", "1")
    )
    assert page_response.status_code == 200
    assert page_response.content.endswith(b"-page-two")
    assert page_response.headers["content-type"].startswith("image/gif")
    assert page_response.headers["cache-control"] == "private, max-age=3600, immutable"

    not_modified = await authenticated_client.get(
        manifest["page_url_template"].replace("{page_index}", "1"),
        headers={"If-None-Match": page_response.headers["etag"]},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""


@pytest.mark.asyncio
async def test_reader_api_rejects_stale_revision_without_file_details(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
    sec_app: object,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.cbz"
    _write_cbz(source)
    issue_id = await _seed_reader_issue(sec_db, source)
    sec_app.state.reader_content_service = ReaderContentService(cache_dir=tmp_path / "cache")

    response = await authenticated_client.get(
        f"/api/v1/reader/issues/{issue_id}/pages/0?revision=stale"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_revision"
    assert str(source) not in response.text


@pytest.mark.asyncio
async def test_progress_is_explicit_private_and_resumed_from_manifest(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
    sec_app: object,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.cbz"
    _write_cbz(source)
    issue_id = await _seed_reader_issue(sec_db, source)
    sec_app.state.reader_content_service = ReaderContentService(cache_dir=tmp_path / "cache")
    manifest_response = await authenticated_client.get(f"/api/v1/reader/issues/{issue_id}/manifest")
    manifest = manifest_response.json()
    session_token = authenticated_client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(session_token) or ""
    payload = {
        "revision": manifest["revision"],
        "page_index": 1,
        "page_count": 2,
        "completion_candidate": True,
    }

    csrf_denied = await authenticated_client.put(
        f"/api/v1/reader/issues/{issue_id}/progress",
        json=payload,
    )
    saved = await authenticated_client.put(
        f"/api/v1/reader/issues/{issue_id}/progress",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    resumed = await authenticated_client.get(f"/api/v1/reader/issues/{issue_id}/manifest")

    assert csrf_denied.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["page_index"] == 1
    assert saved.json()["completed_at"] is not None
    assert resumed.json()["initial_page_index"] == 1


@pytest.mark.asyncio
async def test_page_get_and_manifest_do_not_create_progress_state(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
    sec_user: object,
    sec_app: object,
    tmp_path: Path,
) -> None:
    from sqlalchemy import select

    from pullbox.models.reader import IssueReaderState

    source = tmp_path / "book.cbz"
    _write_cbz(source)
    issue_id = await _seed_reader_issue(sec_db, source)
    sec_app.state.reader_content_service = ReaderContentService(cache_dir=tmp_path / "cache")
    manifest = (await authenticated_client.get(f"/api/v1/reader/issues/{issue_id}/manifest")).json()

    await authenticated_client.get(manifest["page_url_template"].replace("{page_index}", "1"))

    async with sec_db() as session:
        rows = list((await session.execute(select(IssueReaderState))).scalars().all())
    assert rows == []
