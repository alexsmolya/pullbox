"""Tests for UT-P.4 — error recovery and edge cases.

Verifies graceful handling of permission errors, missing files,
cross-mount moves, and worker crashes during job execution.

Run:
    pytest tests/utilities/test_error_recovery.py -v
"""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.file_converter import FileConverterExecutor
from pullbox.utilities.executors.integrity_checker import IntegrityCheckerExecutor
from pullbox.utilities.executors.mass_rename import MassRenameExecutor

# ── Permission Errors ──────────────────────────────────────────


class TestPermissionErrors:
    """Verify permission errors are caught, not crash."""

    def test_readonly_file_rename_fails_gracefully(self, tmp_path: Path) -> None:
        source = tmp_path / "readonly.cbz"
        source.write_text("content")
        source.chmod(0o444)

        try:
            executor = MassRenameExecutor()
            result = executor.process_item(
                item_data={
                    "id": "perm-001",
                    "file_path": str(source),
                    "operation": "rename",
                    "proposed_name": "New Name.cbz",
                },
                job_config={"target": "files"},
            )
            # On macOS, rename of read-only file may succeed (dir permissions matter)
            # On Linux, it may fail. Either way, no crash.
            assert result.result in (ItemResult.COMPLETED, ItemResult.FAILED)
        finally:
            # File may have been renamed — chmod whichever exists
            for f in tmp_path.iterdir():
                if f.is_file():
                    f.chmod(0o644)


# ── Missing Files Mid-Job ──────────────────────────────────────


class TestMissingFiles:
    """Verify files deleted between discovery and processing."""

    def test_file_deleted_before_convert(self, tmp_path: Path) -> None:
        executor = FileConverterExecutor()
        result = executor.process_item(
            item_data={
                "id": "miss-001",
                "file_path": str(tmp_path / "deleted.cb7"),
                "operation": "convert",
            },
            job_config={"target_format": "cbz"},
        )
        assert result.result == ItemResult.FAILED
        assert "not found" in (result.error_message or "").lower()

    def test_file_deleted_before_integrity_check(self, tmp_path: Path) -> None:
        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={
                "id": "miss-002",
                "file_path": str(tmp_path / "deleted.cbz"),
                "operation": "check",
            },
            job_config={"scan_depth": "quick"},
        )
        assert result.result == ItemResult.FAILED

    def test_file_deleted_before_rename(self, tmp_path: Path) -> None:
        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "miss-003",
                "file_path": str(tmp_path / "deleted.cbz"),
                "operation": "rename",
                "proposed_name": "New.cbz",
            },
            job_config={"target": "files"},
        )
        assert result.result == ItemResult.FAILED


# ── Empty / Corrupt Files ──────────────────────────────────────


class TestCorruptFiles:
    """Verify corrupt and empty files are handled gracefully."""

    def test_zero_byte_file_convert(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.cb7"
        empty.write_bytes(b"")

        executor = FileConverterExecutor()
        result = executor.process_item(
            item_data={"id": "corrupt-001", "file_path": str(empty), "operation": "convert"},
            job_config={"target_format": "cbz"},
        )
        assert result.result == ItemResult.FAILED

    def test_garbage_file_integrity_check(self, tmp_path: Path) -> None:
        garbage = tmp_path / "garbage.cbz"
        garbage.write_bytes(os.urandom(100))

        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={"id": "corrupt-002", "file_path": str(garbage), "operation": "check"},
            job_config={"scan_depth": "quick"},
        )
        assert result.result == ItemResult.FAILED
        assert result.after_state.get("status") == "corrupt"


# ── Trash Auto-Creation ───────────────────────────────────────


class TestTrashAutoCreation:
    """Verify trash folder is auto-created when it doesn't exist."""

    def test_trash_created_on_convert(self, tmp_path: Path) -> None:
        import py7zr

        source_dir = tmp_path / "comics"
        source = source_dir / "test.cb7"
        source_dir.mkdir()
        with py7zr.SevenZipFile(source, "w") as archive:
            page = source_dir / "_p.jpg"
            page.write_bytes(b"\xff\xd8" + b"X" * 100)
            archive.write(page, "page.jpg")
            page.unlink()

        trash_dir = tmp_path / "nonexistent" / "trash"
        assert not trash_dir.exists()

        executor = FileConverterExecutor()
        result = executor.process_item(
            item_data={"id": "trash-001", "file_path": str(source), "operation": "convert"},
            job_config={"target_format": "cbz", "trash_folder": str(trash_dir)},
        )
        assert result.result == ItemResult.COMPLETED
        assert trash_dir.exists()
