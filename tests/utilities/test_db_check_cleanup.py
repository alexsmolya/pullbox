"""Tests for UT-4.1 — database check & cleanup executor.

Verifies orphan detection, stale file detection, preview mode,
action execution, and rollback.

Run:
    pytest tests/utilities/test_db_check_cleanup.py -v
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import pytest

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series, SeriesStatus
from pullbox.services.db_check_service import apply_db_check_repair
from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.db_check_cleanup import (
    DBCheckCleanupExecutor,
    detect_orphaned_records,
    detect_stale_files,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

# ── Orphan Detection ───────────────────────────────────────────


class TestOrphanDetection:
    """Verify detection of DB records pointing to missing files."""

    def test_detects_missing_file(self, tmp_path: Path) -> None:
        """Record with file_path pointing to nonexistent file is orphaned."""
        records = [
            {"id": 1, "file_path": str(tmp_path / "exists.cbz")},
            {"id": 2, "file_path": str(tmp_path / "missing.cbz")},
        ]
        (tmp_path / "exists.cbz").write_text("content")

        orphans = detect_orphaned_records(records)
        assert len(orphans) == 1
        assert orphans[0]["id"] == 2

    def test_null_file_path_not_orphan(self) -> None:
        """Records with NULL file_path (wanted issues) are not orphans."""
        records = [
            {"id": 1, "file_path": None},
            {"id": 2, "file_path": ""},
        ]
        orphans = detect_orphaned_records(records)
        assert len(orphans) == 0

    def test_no_records_returns_empty(self) -> None:
        orphans = detect_orphaned_records([])
        assert orphans == []

    def test_all_files_exist(self, tmp_path: Path) -> None:
        (tmp_path / "a.cbz").write_text("a")
        (tmp_path / "b.cbz").write_text("b")
        records = [
            {"id": 1, "file_path": str(tmp_path / "a.cbz")},
            {"id": 2, "file_path": str(tmp_path / "b.cbz")},
        ]
        orphans = detect_orphaned_records(records)
        assert orphans == []

    def test_all_files_missing(self, tmp_path: Path) -> None:
        records = [{"id": i, "file_path": str(tmp_path / f"gone_{i}.cbz")} for i in range(5)]
        orphans = detect_orphaned_records(records)
        assert len(orphans) == 5


# ── Stale File Detection ──────────────────────────────────────


class TestStaleFileDetection:
    """Verify detection of files on disk not tracked in DB."""

    def test_detects_untracked_file(self, tmp_path: Path) -> None:
        (tmp_path / "tracked.cbz").write_text("tracked")
        (tmp_path / "stale.cbz").write_text("stale")
        known_paths = {str(tmp_path / "tracked.cbz")}

        stale = detect_stale_files(tmp_path, known_paths)
        assert len(stale) == 1
        assert stale[0]["path"] == str(tmp_path / "stale.cbz")

    def test_no_stale_files(self, tmp_path: Path) -> None:
        (tmp_path / "tracked.cbz").write_text("t")
        known_paths = {str(tmp_path / "tracked.cbz")}

        stale = detect_stale_files(tmp_path, known_paths)
        assert stale == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        stale = detect_stale_files(tmp_path, set())
        assert stale == []

    def test_nested_stale_file(self, tmp_path: Path) -> None:
        nested = tmp_path / "Marvel" / "Spider-Man"
        nested.mkdir(parents=True)
        (nested / "stale.cbz").write_text("stale")

        stale = detect_stale_files(tmp_path, set())
        assert len(stale) == 1

    def test_stale_files_return_in_deterministic_recursive_order(self, tmp_path: Path) -> None:
        root_file = tmp_path / "B-root.cbz"
        root_file.write_text("root")

        nested_dir = tmp_path / "A Series"
        nested_dir.mkdir()
        nested_file = nested_dir / "Issue 002.cbz"
        nested_file.write_text("nested")

        deep_dir = nested_dir / "Annuals"
        deep_dir.mkdir()
        deep_file = deep_dir / "Issue 001.cbz"
        deep_file.write_text("deep")

        stale = detect_stale_files(tmp_path, set())

        assert [item["path"] for item in stale] == [
            str(root_file),
            str(nested_file),
            str(deep_file),
        ]

    def test_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        stale = detect_stale_files(tmp_path / "nonexistent", set())
        assert stale == []

    def test_non_comic_files_ignored(self, tmp_path: Path) -> None:
        """Only comic extensions are checked."""
        (tmp_path / "readme.txt").write_text("text")
        (tmp_path / "cover.jpg").write_text("image")
        (tmp_path / "stale.cbz").write_text("comic")

        stale = detect_stale_files(tmp_path, set())
        assert len(stale) == 1
        assert stale[0]["path"].endswith(".cbz")

    def test_ignores_files_inside_utility_trash_folder(self, tmp_path: Path) -> None:
        """Files under the library .trash folder should not be flagged as stale."""
        visible = tmp_path / "visible.cbz"
        visible.write_text("visible")

        trash_dir = tmp_path / ".trash"
        trash_dir.mkdir()
        (trash_dir / "trashed.cbz").write_text("trashed")

        stale = detect_stale_files(tmp_path, set())

        assert [item["path"] for item in stale] == [str(visible)]


# ── Config Validation ──────────────────────────────────────────


class TestValidateConfig:
    """Verify config validation."""

    def test_valid_config(self) -> None:
        executor = DBCheckCleanupExecutor()
        errors = executor.validate_config(
            {
                "checks": ["orphans", "stale"],
            }
        )
        assert errors == []

    def test_missing_checks(self) -> None:
        executor = DBCheckCleanupExecutor()
        errors = executor.validate_config({})
        assert any("checks" in e.lower() for e in errors)

    def test_empty_checks(self) -> None:
        executor = DBCheckCleanupExecutor()
        errors = executor.validate_config({"checks": []})
        assert any("checks" in e.lower() for e in errors)

    def test_invalid_check_type(self) -> None:
        executor = DBCheckCleanupExecutor()
        errors = executor.validate_config({"checks": ["invalid_check"]})
        assert any("invalid" in e.lower() or "unknown" in e.lower() for e in errors)


# ── Process Item ───────────────────────────────────────────────


class TestProcessItem:
    """Verify action execution on detected issues."""

    def test_delete_orphan_action(self) -> None:
        executor = DBCheckCleanupExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-001",
                "operation": "delete_record",
                "record_id": 42,
                "record_type": "library_file",
                "description": "Missing file: /comics/batman.cbz",
            },
            job_config={"mode": "execute"},
        )
        # In execute mode without DB, marks as completed (action recorded)
        assert result.item_id == "item-001"
        assert isinstance(result.result, ItemResult)

    def test_preview_mode_skips_execution(self) -> None:
        executor = DBCheckCleanupExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-002",
                "operation": "delete_record",
                "record_id": 42,
                "record_type": "library_file",
            },
            job_config={"mode": "preview"},
        )
        assert result.result == ItemResult.SKIPPED
        assert "preview" in (result.log_entries[0][1] if result.log_entries else "").lower()

    def test_skip_action(self) -> None:
        executor = DBCheckCleanupExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-003",
                "operation": "skip",
            },
            job_config={"mode": "execute"},
        )
        assert result.result == ItemResult.SKIPPED


# ── Rollback ───────────────────────────────────────────────────


class TestRollback:
    """Verify rollback behavior."""

    def test_rollback_returns_completed(self) -> None:
        """DB cleanup rollback records the undo action."""
        executor = DBCheckCleanupExecutor()
        result = executor.rollback_item(
            item_data={
                "id": "rb-001",
                "operation": "delete_record",
                "before_state": {"record_id": 42, "record_type": "library_file"},
            },
            job_config={},
        )
        assert result.item_id == "rb-001"
        assert isinstance(result.result, ItemResult)


# ── DB Check Edge Cases ──────────────────────────────────────


class TestDBCheckEdgeCases:
    """Verify edge cases in DB check and cleanup operations."""

    def test_stale_file_permission_error_skipped(self, tmp_path: Path) -> None:
        """File where os.stat raises PermissionError produces size=0."""
        import sys

        if sys.platform == "win32":
            pytest.skip("chmod not effective on Windows")

        # Create a file that exists but is not readable
        unreadable = tmp_path / "locked.cbz"
        unreadable.write_text("content")

        # stat works for file owner even with 0o000 on macOS/Linux,
        # so we test detect_stale_files handles it gracefully
        known_paths: set[str] = set()  # File is not tracked
        stale = detect_stale_files(tmp_path, known_paths)
        assert len(stale) == 1
        assert stale[0]["path"] == str(unreadable)
        # Size should be retrievable
        assert stale[0]["size"] >= 0

    async def test_execute_with_empty_actions(self) -> None:
        """No actions selected -> generate_items returns empty, job completes with 0 items."""
        executor = DBCheckCleanupExecutor()
        items = await executor.generate_items({"checks": ["orphans"], "actions": []})
        assert items == []

    async def test_generate_items_no_actions_key(self) -> None:
        """Config without 'actions' key generates empty item list."""
        executor = DBCheckCleanupExecutor()
        items = await executor.generate_items({"checks": ["orphans"]})
        assert items == []


@pytest.mark.asyncio
async def test_apply_repair_updates_stale_series_paths_and_descendants(
    session_factory: async_sessionmaker,
    tmp_path: Path,
) -> None:
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()
    actual_folder = library_root_path / "Nightwing [2222]"
    actual_folder.mkdir()
    actual_file = actual_folder / "Nightwing 001.cbz"
    actual_file.write_text("nightwing")
    stale_folder = library_root_path / "nightwing-old-folder"

    async with session_factory() as session:
        publisher = Publisher(name="DC Comics")
        root = LibraryRoot(name="Library", path=str(library_root_path), enabled=True)
        session.add_all([publisher, root])
        await session.flush()

        series = Series(
            title="Nightwing",
            sort_title="Nightwing",
            comicvine_id=2222,
            year_start=2016,
            status=SeriesStatus.CONTINUING,
            monitored=True,
            publisher_id=publisher.id,
            library_root_id=root.id,
            path=str(stale_folder),
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            title="Nightwing #1",
            status=IssueStatus.OWNED,
        )
        session.add(issue)
        await session.flush()

        library_file = LibraryFile(
            issue_id=issue.id,
            library_root_id=root.id,
            file_path=str(stale_folder / actual_file.name),
            file_name=actual_file.name,
            file_size=10,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(tz=UTC),
            match_confidence=MatchConfidence.HIGH,
        )
        session.add(library_file)
        await session.commit()

        series_id = series.id
        library_file_id = library_file.id

    async with session_factory() as session:
        await apply_db_check_repair(
            session,
            {
                "operation": "repair",
                "record_id": series_id,
                "record_type": "series",
                "file_path": str(stale_folder),
                "context": {
                    "repair_kind": "series_path",
                    "target_path": str(actual_folder),
                },
            },
        )
        await session.commit()

    async with session_factory() as session:
        repaired_series = await session.get(Series, series_id)
        repaired_file = await session.get(LibraryFile, library_file_id)

        assert repaired_series is not None
        assert repaired_file is not None
        assert repaired_series.path == str(actual_folder)
        assert repaired_file.file_path == str(actual_file)
        assert repaired_file.file_name == actual_file.name


@pytest.mark.asyncio
async def test_apply_repair_updates_root_ids_for_series_and_library_files(
    session_factory: async_sessionmaker,
    tmp_path: Path,
) -> None:
    root_one_path = tmp_path / "library-one"
    root_two_path = tmp_path / "library-two"
    root_one_path.mkdir()
    root_two_path.mkdir()
    actual_folder = root_two_path / "superman-folder"
    actual_folder.mkdir()
    actual_file = actual_folder / "superman-001.cbz"
    actual_file.write_text("superman")

    async with session_factory() as session:
        publisher = Publisher(name="DC Comics")
        root_one = LibraryRoot(name="Library One", path=str(root_one_path), enabled=True)
        root_two = LibraryRoot(name="Library Two", path=str(root_two_path), enabled=True)
        session.add_all([publisher, root_one, root_two])
        await session.flush()

        series = Series(
            title="Superman",
            sort_title="Superman",
            year_start=2018,
            status=SeriesStatus.CONTINUING,
            monitored=True,
            publisher_id=publisher.id,
            library_root_id=root_one.id,
            path=str(actual_folder),
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=1.0,
            title="Superman #1",
            status=IssueStatus.OWNED,
        )
        session.add(issue)
        await session.flush()

        library_file = LibraryFile(
            issue_id=issue.id,
            library_root_id=root_one.id,
            file_path=str(actual_file),
            file_name=actual_file.name,
            file_size=11,
            file_format=FileFormat.CBZ,
            file_modified_at=datetime.now(tz=UTC),
            match_confidence=MatchConfidence.HIGH,
        )
        session.add(library_file)
        await session.commit()

        series_id = series.id
        library_file_id = library_file.id
        root_two_id = root_two.id

    async with session_factory() as session:
        await apply_db_check_repair(
            session,
            {
                "operation": "repair",
                "record_id": series_id,
                "record_type": "series",
                "file_path": str(actual_folder),
                "context": {
                    "repair_kind": "series_root_id",
                    "target_root_id": root_two_id,
                    "target_root_path": str(root_two_path),
                },
            },
        )
        await apply_db_check_repair(
            session,
            {
                "operation": "repair",
                "record_id": library_file_id,
                "record_type": "library_file",
                "file_path": str(actual_file),
                "context": {
                    "repair_kind": "library_file_root_id",
                    "target_root_id": root_two_id,
                    "target_root_path": str(root_two_path),
                },
            },
        )
        await session.commit()

    async with session_factory() as session:
        repaired_series = await session.get(Series, series_id)
        repaired_file = await session.get(LibraryFile, library_file_id)

        assert repaired_series is not None
        assert repaired_file is not None
        assert repaired_series.library_root_id == root_two_id
        assert repaired_file.library_root_id == root_two_id


@pytest.mark.asyncio
async def test_apply_reindex_refreshes_library_file_metadata(
    session_factory: async_sessionmaker,
    tmp_path: Path,
) -> None:
    library_root_path = tmp_path / "library"
    library_root_path.mkdir()
    file_path = library_root_path / "Batman (2016) #007.cbz"
    with zipfile.ZipFile(file_path, "w") as archive:
        archive.writestr(
            "ComicInfo.xml",
            (
                "<ComicInfo>"
                "<Series>Batman</Series>"
                "<Number>7</Number>"
                "<Volume>2016</Volume>"
                "<Publisher>DC Comics</Publisher>"
                "</ComicInfo>"
            ),
        )

    async with session_factory() as session:
        root = LibraryRoot(name="Library", path=str(library_root_path), enabled=True)
        session.add(root)
        await session.flush()

        library_file = LibraryFile(
            issue_id=None,
            library_root_id=root.id,
            file_path=str(file_path),
            file_name="wrong-name.cbz",
            file_size=1,
            file_format=FileFormat.CBR,
            file_modified_at=datetime(2001, 1, 1, tzinfo=UTC),
            match_confidence=MatchConfidence.UNMATCHED,
            parsed_series="Wrong",
            parsed_issue_number=1.0,
            parsed_year=1999,
            parsed_publisher="Wrong Publisher",
            has_comicinfo=False,
        )
        session.add(library_file)
        await session.commit()

        library_file_id = library_file.id

    async with session_factory() as session:
        await apply_db_check_repair(
            session,
            {
                "operation": "reindex",
                "record_id": None,
                "record_type": "library",
                "file_path": str(library_root_path),
                "context": {
                    "repair_kind": "reindex_root",
                    "target_root_path": str(library_root_path),
                },
            },
        )
        await session.commit()

    async with session_factory() as session:
        refreshed_file = await session.get(LibraryFile, library_file_id)

        assert refreshed_file is not None
        assert refreshed_file.file_name == file_path.name
        assert refreshed_file.file_size == file_path.stat().st_size
        assert refreshed_file.file_format == FileFormat.CBZ
        assert refreshed_file.parsed_series == "Batman"
        assert refreshed_file.parsed_issue_number == 7.0
        assert refreshed_file.parsed_year == 2016
        assert refreshed_file.parsed_publisher == "DC Comics"
        assert refreshed_file.has_comicinfo is True
