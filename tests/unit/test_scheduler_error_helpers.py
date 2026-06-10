"""Tests for pure scheduler error-classification helpers."""

from __future__ import annotations

from pullbox.core.scheduler_error_helpers import (
    is_locked_error,
    is_missing_task_stats_table_error,
    is_unusable_persist_error,
    logical_task_id,
)


def test_is_locked_error_detects_sqlite_lock_messages() -> None:
    assert is_locked_error(Exception("database is locked"))
    assert is_locked_error(Exception("locking protocol"))
    assert not is_locked_error(Exception("network timeout"))


def test_is_missing_task_stats_table_error_detects_specific_table() -> None:
    assert is_missing_task_stats_table_error(Exception("no such table: scheduled_task_stats"))
    assert not is_missing_task_stats_table_error(Exception("no such table: issues"))


def test_is_unusable_persist_error_detects_unrecoverable_db_failures() -> None:
    assert is_unusable_persist_error(Exception("database disk image is malformed"))
    assert is_unusable_persist_error(Exception("file is not a database"))
    assert is_unusable_persist_error(Exception("disk I/O error"))
    assert not is_unusable_persist_error(Exception("database is locked"))


def test_logical_task_id_removes_manual_suffix_only() -> None:
    assert logical_task_id("process_completed_manual") == "process_completed"
    assert logical_task_id("process_completed") == "process_completed"
