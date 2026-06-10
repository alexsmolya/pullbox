"""Tests for UT-P.1 — rollback end-to-end across all features.

Verifies the complete lifecycle: submit → complete → rollback → verify
for each feature executor (converter, rename, export).

Run:
    pytest tests/utilities/test_rollback_e2e.py -v
"""

from __future__ import annotations

from pathlib import Path

import py7zr

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.export_library import ExportLibraryExecutor
from pullbox.utilities.executors.file_converter import FileConverterExecutor
from pullbox.utilities.executors.mass_rename import MassRenameExecutor

# ── File Converter Rollback ────────────────────────────────────


class TestConverterRollback:
    """Verify convert → rollback restores original file from trash."""

    def test_convert_then_rollback(self, tmp_path: Path) -> None:
        # Create source file
        source_dir = tmp_path / "comics"
        source_dir.mkdir()
        source = source_dir / "batman.cb7"
        with py7zr.SevenZipFile(source, "w") as archive:
            tmp_file = source_dir / "_page.jpg"
            tmp_file.write_bytes(b"\xff\xd8" + b"X" * 500)
            archive.write(tmp_file, "page_000.jpg")
            tmp_file.unlink()

        trash_dir = tmp_path / ".trash"

        # Step 1: Convert
        executor = FileConverterExecutor()
        convert_result = executor.process_item(
            item_data={"id": "item-001", "file_path": str(source), "operation": "convert"},
            job_config={"target_format": "cbz", "trash_folder": str(trash_dir)},
        )
        assert convert_result.result == ItemResult.COMPLETED
        converted = Path(convert_result.after_state["path"])
        assert converted.exists()
        assert not source.exists()  # Original moved to trash

        # Step 2: Rollback
        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-001",
                "before_state": convert_result.before_state,
                "after_state": convert_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.COMPLETED
        assert not converted.exists()  # Converted file removed
        assert (source_dir / "batman.cb7").exists()  # Original restored

    def test_rollback_after_trash_emptied(self, tmp_path: Path) -> None:
        """Rollback when trash is empty fails per-item."""
        source_dir = tmp_path / "comics"
        source_dir.mkdir()
        source = source_dir / "saga.cb7"
        with py7zr.SevenZipFile(source, "w") as archive:
            tmp_file = source_dir / "_page.jpg"
            tmp_file.write_bytes(b"\xff\xd8" + b"X" * 500)
            archive.write(tmp_file, "page_000.jpg")
            tmp_file.unlink()

        trash_dir = tmp_path / ".trash"

        executor = FileConverterExecutor()
        convert_result = executor.process_item(
            item_data={"id": "item-002", "file_path": str(source), "operation": "convert"},
            job_config={"target_format": "cbz", "trash_folder": str(trash_dir)},
        )
        assert convert_result.result == ItemResult.COMPLETED

        # Empty the trash
        for f in trash_dir.rglob("*"):
            if f.is_file():
                f.unlink()

        # Rollback should fail (original is gone)
        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-002",
                "before_state": convert_result.before_state,
                "after_state": convert_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.FAILED
        assert Path(convert_result.after_state["path"]).exists()


# ── Mass Rename Rollback ───────────────────────────────────────


class TestRenameRollback:
    """Verify rename → rollback restores original names."""

    def test_rename_then_rollback(self, tmp_path: Path) -> None:
        source = tmp_path / "old_name.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        rename_result = executor.process_item(
            item_data={
                "id": "item-010",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman (2016) #001.cbz",
            },
            job_config={"target": "files"},
        )
        assert rename_result.result == ItemResult.COMPLETED
        renamed = tmp_path / "Batman (2016) #001.cbz"
        assert renamed.exists()
        assert not source.exists()

        # Rollback
        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-010",
                "before_state": rename_result.before_state,
                "after_state": rename_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.COMPLETED
        assert source.exists()
        assert not renamed.exists()

    def test_folder_rename_then_rollback(self, tmp_path: Path) -> None:
        folder = tmp_path / "batman-2016"
        folder.mkdir()
        (folder / "issue.cbz").write_text("content")

        executor = MassRenameExecutor()
        rename_result = executor.process_item(
            item_data={
                "id": "item-011",
                "file_path": str(folder),
                "operation": "rename",
                "proposed_name": "Batman (2016)",
            },
            job_config={"target": "folders"},
        )
        assert rename_result.result == ItemResult.COMPLETED

        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-011",
                "before_state": rename_result.before_state,
                "after_state": rename_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.COMPLETED
        assert folder.exists()
        assert (folder / "issue.cbz").exists()


# ── Export Rollback ────────────────────────────────────────────


class TestExportRollback:
    """Verify export → rollback deletes the exported file."""

    def test_export_then_rollback(self, tmp_path: Path) -> None:
        records = [
            {"series_name": "Batman", "year": 2016},
            {"series_name": "Saga", "year": 2012},
        ]

        executor = ExportLibraryExecutor()
        export_result = executor.process_item(
            item_data={"id": "item-020", "operation": "export", "records": records},
            job_config={
                "format": "json",
                "fields": ["series_name", "year"],
                "export_folder": str(tmp_path),
            },
        )
        assert export_result.result == ItemResult.COMPLETED
        export_path = Path(export_result.after_state["path"])
        assert export_path.exists()

        # Rollback deletes the file
        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-020",
                "after_state": export_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.COMPLETED
        assert not export_path.exists()

    def test_rollback_already_deleted_export(self, tmp_path: Path) -> None:
        """Rollback when export file is already gone."""
        executor = ExportLibraryExecutor()
        rollback_result = executor.rollback_item(
            item_data={
                "id": "item-021",
                "after_state": {"path": str(tmp_path / "gone.json")},
            },
            job_config={},
        )
        # File doesn't exist, but rollback still "succeeds" (nothing to undo)
        assert rollback_result.result == ItemResult.COMPLETED


# ── Rollback Edge Cases ───────────────────────────────────────


class TestRollbackEdgeCases:
    """Verify rollback edge cases at the state machine and executor levels."""

    def test_double_rollback_prevented(self) -> None:
        """After rollback completes, ROLLED_BACK is terminal — no further transitions."""
        from pullbox.utilities.job_queue import VALID_TRANSITIONS, JobQueueManager
        from pullbox.utilities.models import JobState

        # Verify at the state machine level
        assert VALID_TRANSITIONS[JobState.ROLLED_BACK] == set()

        # Also verify via the transition method
        mgr = JobQueueManager.__new__(JobQueueManager)
        from pullbox.utilities.models import UtilityJob

        job = UtilityJob(
            id="rb-double",
            job_type="rollback",
            display_name="Test",
            state=JobState.ROLLED_BACK,
            config="{}",
            total_items=0,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
        )

        import pytest as _pytest

        # Cannot transition ROLLED_BACK to anything
        with _pytest.raises(ValueError, match="none \\(terminal\\)"):
            mgr.transition(job, JobState.ROLLING_BACK)

    def test_db_check_rollback(self, tmp_path: Path) -> None:
        """DB check execute then rollback: verify action recorded."""
        from pullbox.utilities.executors.db_check_cleanup import DBCheckCleanupExecutor

        executor = DBCheckCleanupExecutor()

        # Step 1: Execute action
        exec_result = executor.process_item(
            item_data={
                "id": "db-item-001",
                "operation": "delete_record",
                "record_id": 99,
                "record_type": "library_file",
                "description": "Orphaned record",
            },
            job_config={"mode": "execute"},
        )
        assert exec_result.result == ItemResult.COMPLETED
        assert exec_result.before_state.get("record_id") == 99

        # Step 2: Rollback
        rollback_result = executor.rollback_item(
            item_data={
                "id": "db-item-001",
                "operation": "delete_record",
                "before_state": exec_result.before_state,
                "after_state": exec_result.after_state,
            },
            job_config={},
        )
        assert rollback_result.result == ItemResult.COMPLETED
        # Check rollback log entry recorded
        assert len(rollback_result.log_entries) >= 1
        assert "rollback" in rollback_result.log_entries[0][1].lower()


# ── Rollback State Machine Edge Cases ──────────────────────────


class TestRollbackStateMachine:
    """Verify rollback state transitions prevent double-rollback."""

    def test_rolled_back_is_terminal(self) -> None:
        """ROLLED_BACK state has no valid transitions (terminal)."""
        from pullbox.utilities.job_queue import VALID_TRANSITIONS
        from pullbox.utilities.models import JobState

        assert VALID_TRANSITIONS[JobState.ROLLED_BACK] == set()

    def test_double_rollback_blocked_by_state_machine(self) -> None:
        """Cannot transition from ROLLED_BACK to ROLLING_BACK."""
        from pullbox.utilities.job_queue import JobQueueManager
        from pullbox.utilities.models import JobState, UtilityJob

        mgr = JobQueueManager.__new__(JobQueueManager)
        job = UtilityJob(
            id="dbl-rb",
            job_type="rollback",
            display_name="Already Rolled Back",
            state=JobState.ROLLED_BACK,
            total_items=0,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
        )

        import pytest

        with pytest.raises(ValueError, match="terminal"):
            mgr.transition(job, JobState.ROLLING_BACK)
