"""Focused API coverage for library browser entry actions."""

from __future__ import annotations

import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from pullbox.models.config import SystemConfig
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-library-browser-api")


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


def _write_zip_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page_0001.txt", "convert me")


@pytest.fixture
async def seeded_library_browser_data(
    sec_db: async_sessionmaker,
    tmp_path: Path,
) -> dict[str, Path]:
    root_path = tmp_path / "library"
    root_path.mkdir(parents=True)

    collection_folder = root_path / "Collections"
    collection_folder.mkdir()

    series_folder = collection_folder / "Series Folder"
    series_folder.mkdir()
    series_file = series_folder / "Issue 001.cbz"
    series_file.write_bytes(b"series-file")

    series_without_issues_folder = collection_folder / "Series Without Issues (2012) [50771]"
    series_without_issues_folder.mkdir()
    stale_series_file = series_without_issues_folder / "Issue 002.cbz"
    stale_series_file.write_bytes(b"stale-series-file")

    loose_file = root_path / "Loose File.cbz"
    loose_file.write_bytes(b"loose")

    convertible_file = root_path / "Convert Me.cbr"
    _write_zip_archive(convertible_file)

    trash_dir = tmp_path / ".trash"
    trash_dir.mkdir()

    async with sec_db() as session:
        root = LibraryRoot(name="Primary Root", path=str(root_path), enabled=True)
        session.add(root)
        session.add(
            SystemConfig(
                key="utility_trash_folder",
                value=str(trash_dir),
                value_type="string",
            )
        )
        await session.flush()

        series = Series(
            title="Series Folder",
            sort_title="series folder",
            path=str(series_folder),
            library_root_id=root.id,
            monitored=True,
        )
        session.add(series)
        session.add(
            Series(
                title="Series Without Issues",
                sort_title="series without issues",
                comicvine_id=50771,
                path=str(collection_folder / "Series Without Issues (2012)"),
                library_root_id=root.id,
                monitored=False,
            )
        )
        await session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            status=IssueStatus.OWNED,
        )
        session.add(issue)
        await session.flush()

        session.add_all(
            [
                LibraryFile(
                    library_root_id=root.id,
                    file_path=str(loose_file),
                    file_name=loose_file.name,
                    file_size=loose_file.stat().st_size,
                    file_format=FileFormat.CBZ,
                    file_modified_at=datetime.fromtimestamp(loose_file.stat().st_mtime, tz=UTC),
                    match_confidence=MatchConfidence.UNMATCHED,
                    has_comicinfo=False,
                ),
                LibraryFile(
                    library_root_id=root.id,
                    file_path=str(series_file),
                    file_name=series_file.name,
                    file_size=series_file.stat().st_size,
                    file_format=FileFormat.CBZ,
                    file_modified_at=datetime.fromtimestamp(series_file.stat().st_mtime, tz=UTC),
                    match_confidence=MatchConfidence.MANUAL,
                    has_comicinfo=False,
                    issue_id=issue.id,
                ),
                LibraryFile(
                    library_root_id=root.id,
                    file_path=str(convertible_file),
                    file_name=convertible_file.name,
                    file_size=convertible_file.stat().st_size,
                    file_format=FileFormat.CBR,
                    file_modified_at=datetime.fromtimestamp(
                        convertible_file.stat().st_mtime, tz=UTC
                    ),
                    match_confidence=MatchConfidence.UNMATCHED,
                    has_comicinfo=False,
                ),
            ]
        )
        await session.commit()

    return {
        "root_path": root_path,
        "collection_folder": collection_folder,
        "series_folder": series_folder,
        "series_file": series_file,
        "series_without_issues_folder": series_without_issues_folder,
        "stale_series_file": stale_series_file,
        "loose_file": loose_file,
        "convertible_file": convertible_file,
        "trash_dir": trash_dir,
    }


@pytest.mark.asyncio
async def test_library_browser_entry_returns_real_metadata_and_actions(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get(
        "/api/v1/library/browser/entry",
        params={"path": str(seeded_library_browser_data["convertible_file"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Convert Me.cbr"
    assert data["kind"] == "file"
    assert data["root_name"] == "Primary Root"
    assert data["actions"]["can_properties"] is True
    assert data["actions"]["can_rename"] is True
    assert data["actions"]["can_auto_rename"] is True
    assert data["actions"]["can_convert"] is True
    assert data["actions"]["can_delete"] is True
    assert data["delete_context"]["mode"] == "file"
    assert data["delete_context"]["trash_enabled"] is True
    assert data["delete_context"]["has_linked_issue"] is False
    assert data["delete_context"]["issue_status_after_delete"] is None
    assert data["rename_context"]["stale_reference"] is False


@pytest.mark.asyncio
async def test_library_browser_entry_reports_post_delete_issue_status_for_tracked_file(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get(
        "/api/v1/library/browser/entry",
        params={"path": str(seeded_library_browser_data["series_file"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "file"
    assert data["delete_context"]["mode"] == "file"
    assert data["delete_context"]["tracked_file_count"] == 1
    assert data["delete_context"]["has_linked_issue"] is True
    assert data["delete_context"]["issue_status_after_delete"] == "wanted"
    assert data["delete_context"]["issue_status_reason"] == "series_monitored"


@pytest.mark.asyncio
async def test_library_browser_entry_detects_series_folder_delete_context(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get(
        "/api/v1/library/browser/entry",
        params={"path": str(seeded_library_browser_data["series_folder"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "folder"
    assert data["delete_context"]["mode"] == "series"
    assert data["delete_context"]["series_title"] == "Series Folder"
    assert data["delete_context"]["linked_file_count"] == 1


@pytest.mark.asyncio
async def test_library_browser_entry_detects_series_folder_without_issues(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get(
        "/api/v1/library/browser/entry",
        params={"path": str(seeded_library_browser_data["series_without_issues_folder"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "folder"
    assert data["delete_context"]["mode"] == "series"
    assert data["delete_context"]["series_title"] == "Series Without Issues"
    assert data["delete_context"]["linked_file_count"] == 0
    assert data["rename_context"]["stale_reference"] is True
    assert data["rename_context"]["reason_code"] == "stale_series_path"


@pytest.mark.asyncio
async def test_library_browser_entry_detects_stale_series_file_for_rename(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get(
        "/api/v1/library/browser/entry",
        params={"path": str(seeded_library_browser_data["stale_series_file"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "file"
    assert data["rename_context"]["stale_reference"] is True
    assert data["rename_context"]["reason_code"] == "stale_series_path"


@pytest.mark.asyncio
async def test_library_manual_rename_validation_rejects_extension_change(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.post(
        "/api/v1/library/browser/rename/manual/validate",
        json={
            "path": str(seeded_library_browser_data["convertible_file"]),
            "proposed_name": "Convert Me.cbz",
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "File rename must keep the existing extension."


@pytest.mark.asyncio
async def test_library_convert_executes_immediately_and_updates_tracked_file_record(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    original_file = seeded_library_browser_data["convertible_file"]
    converted_file = original_file.with_suffix(".cbz")

    response = await authenticated_client.post(
        "/api/v1/library/browser/convert",
        json={"path": str(original_file)},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["source_path"] == str(original_file)
    assert payload["target_path"] == str(converted_file)
    assert payload["original_trash_path"].startswith(str(seeded_library_browser_data["trash_dir"]))
    assert original_file.exists() is False
    assert converted_file.exists() is True
    assert Path(payload["original_trash_path"]).exists() is True

    async with sec_db() as session:
        library_file = (
            await session.execute(
                select(LibraryFile).where(LibraryFile.file_path == str(converted_file))
            )
        ).scalar_one()
        assert library_file.file_name == converted_file.name
        assert library_file.file_format == FileFormat.CBZ
        assert library_file.file_size == converted_file.stat().st_size


@pytest.mark.asyncio
async def test_library_convert_rejects_folder_targets(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.post(
        "/api/v1/library/browser/convert",
        json={"path": str(seeded_library_browser_data["collection_folder"])},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Only files can be converted from the browser."


@pytest.mark.asyncio
async def test_library_manual_rename_validation_rejects_stale_series_folder(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.post(
        "/api/v1/library/browser/rename/manual/validate",
        json={
            "path": str(seeded_library_browser_data["series_without_issues_folder"]),
            "proposed_name": "Series Without Issues (2012) [50771] Renamed",
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 422
    assert (
        "stored series path does not match the folder on disk"
        in response.json()["error"]["message"].lower()
    )


@pytest.mark.asyncio
async def test_library_manual_rename_validation_rejects_file_inside_stale_series_folder(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.post(
        "/api/v1/library/browser/rename/manual/validate",
        json={
            "path": str(seeded_library_browser_data["stale_series_file"]),
            "proposed_name": "Issue 002 Renamed.cbz",
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 422
    message = response.json()["error"]["message"].lower()
    assert "stale database path" in message or "series folder with a stale database path" in message


@pytest.mark.asyncio
async def test_library_manual_rename_executes_immediately_and_updates_tracked_file_record(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    original_file = seeded_library_browser_data["loose_file"]
    renamed_file = original_file.with_name("Loose File Deluxe.cbz")

    response = await authenticated_client.post(
        "/api/v1/library/browser/rename",
        json={
            "path": str(original_file),
            "proposed_name": renamed_file.name,
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["source_path"] == str(original_file)
    assert payload["target_path"] == str(renamed_file)
    assert original_file.exists() is False
    assert renamed_file.exists() is True

    async with sec_db() as session:
        library_file = (
            await session.execute(
                select(LibraryFile).where(LibraryFile.file_name == renamed_file.name)
            )
        ).scalar_one()
        assert library_file.file_path == str(renamed_file)
        assert library_file.file_name == renamed_file.name


@pytest.mark.asyncio
async def test_library_folder_rename_updates_descendant_series_and_file_paths(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    original_folder = seeded_library_browser_data["collection_folder"]
    original_series_folder = seeded_library_browser_data["series_folder"]
    original_series_file = seeded_library_browser_data["series_file"]
    renamed_folder = original_folder.with_name("Collections Deluxe")

    response = await authenticated_client.post(
        "/api/v1/library/browser/rename",
        json={
            "path": str(original_folder),
            "proposed_name": renamed_folder.name,
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "folder"
    assert payload["source_path"] == str(original_folder)
    assert payload["target_path"] == str(renamed_folder)
    assert original_folder.exists() is False
    assert renamed_folder.exists() is True
    assert (renamed_folder / original_series_folder.name).exists() is True
    assert (
        renamed_folder / original_series_folder.name / original_series_file.name
    ).exists() is True

    async with sec_db() as session:
        series = (
            await session.execute(select(Series).where(Series.title == "Series Folder"))
        ).scalar_one()
        stale_series = (
            await session.execute(select(Series).where(Series.title == "Series Without Issues"))
        ).scalar_one()
        library_file = (
            await session.execute(
                select(LibraryFile).where(LibraryFile.file_name == original_series_file.name)
            )
        ).scalar_one()

        assert series.path == str(renamed_folder / original_series_folder.name)
        assert stale_series.path == str(renamed_folder / "Series Without Issues (2012)")
        assert library_file.file_path == str(
            renamed_folder / original_series_folder.name / original_series_file.name
        )
        assert library_file.file_name == original_series_file.name


@pytest.mark.asyncio
async def test_library_delete_moves_tracked_file_and_updates_issue_status(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    tracked_file = seeded_library_browser_data["series_file"]

    response = await authenticated_client.post(
        "/api/v1/library/browser/delete",
        json={"path": str(tracked_file)},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["mode"] == "file"
    assert payload["deleted_via_trash"] is True
    assert tracked_file.exists() is False
    assert Path(payload["result_path"]).exists() is True

    async with sec_db() as session:
        remaining = await session.execute(
            select(LibraryFile).where(LibraryFile.file_path == str(tracked_file))
        )
        issue = (await session.execute(select(Issue).where(Issue.issue_number == 1.0))).scalar_one()
        assert remaining.scalar_one_or_none() is None
        assert issue.status == IssueStatus.WANTED


@pytest.mark.asyncio
async def test_library_delete_generic_folder_clears_series_tracking(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    folder = seeded_library_browser_data["collection_folder"]
    child_file = seeded_library_browser_data["series_file"]

    response = await authenticated_client.post(
        "/api/v1/library/browser/delete",
        json={"path": str(folder)},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "folder"
    assert payload["mode"] == "folder"
    assert folder.exists() is False
    assert child_file.exists() is False
    assert Path(payload["result_path"]).exists() is True

    async with sec_db() as session:
        series = (
            await session.execute(select(Series).where(Series.title == "Series Folder"))
        ).scalar_one()
        issue = (await session.execute(select(Issue).where(Issue.issue_number == 1.0))).scalar_one()
        library_file = (
            await session.execute(
                select(LibraryFile).where(LibraryFile.file_path == str(child_file))
            )
        ).scalar_one_or_none()
        assert series.path is None
        assert library_file is None
        assert issue.status == IssueStatus.WANTED


@pytest.mark.asyncio
async def test_library_delete_series_folder_routes_to_series_delete_behavior(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    folder = seeded_library_browser_data["series_folder"]
    child_file = seeded_library_browser_data["series_file"]

    response = await authenticated_client.post(
        "/api/v1/library/browser/delete",
        json={
            "path": str(folder),
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "series"
    assert folder.exists() is False
    assert child_file.exists() is False

    async with sec_db() as session:
        series = (
            await session.execute(select(Series).where(Series.title == "Series Folder"))
        ).scalar_one_or_none()
        assert series is None


@pytest.mark.asyncio
async def test_library_delete_series_folder_without_issues_uses_series_path(
    authenticated_client,
    seeded_library_browser_data: dict[str, Path],
    sec_db: async_sessionmaker,
) -> None:  # type: ignore[no-untyped-def]
    folder = seeded_library_browser_data["series_without_issues_folder"]

    response = await authenticated_client.post(
        "/api/v1/library/browser/delete",
        json={
            "path": str(folder),
        },
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "series"
    assert folder.exists() is False

    async with sec_db() as session:
        series = (
            await session.execute(select(Series).where(Series.title == "Series Without Issues"))
        ).scalar_one_or_none()
        assert series is None
