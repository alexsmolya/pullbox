"""Tests for system log file API helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.api.v1.system_logs import (
    clear_log_paths,
    list_log_file_responses,
    matches_level,
    read_log_content,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_list_log_file_responses_returns_log_files_newest_first(tmp_path: Path) -> None:
    old_log = tmp_path / "pullbox.log.1"
    old_log.write_text("old\n", encoding="utf-8")
    new_log = tmp_path / "pullbox.log"
    new_log.write_text("new\n", encoding="utf-8")
    ignored = tmp_path / "pullbox.txt"
    ignored.write_text("ignored\n", encoding="utf-8")

    rows = list_log_file_responses(tmp_path)

    assert [row.filename for row in rows] == ["pullbox.log", "pullbox.log.1"]
    assert rows[0].size_bytes == 4


def test_read_log_content_returns_tail_and_truncation_flag(tmp_path: Path) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    response = read_log_content(tmp_path, "pullbox.log", tail=2)

    assert response.filename == "pullbox.log"
    assert response.total_lines == 3
    assert response.lines == ["two", "three"]
    assert response.truncated is True


def test_clear_log_paths_deletes_only_log_files(tmp_path: Path) -> None:
    (tmp_path / "pullbox.log").write_text("one\n", encoding="utf-8")
    (tmp_path / "pullbox.log.1").write_text("two\n", encoding="utf-8")
    keep = tmp_path / "notes.txt"
    keep.write_text("keep\n", encoding="utf-8")

    response = clear_log_paths(tmp_path)

    assert response == {"message": "Cleared 2 log files."}
    assert keep.exists()
    assert not (tmp_path / "pullbox.log").exists()
    assert not (tmp_path / "pullbox.log.1").exists()


def test_matches_level_keeps_error_filter_critical_compatibility() -> None:
    assert matches_level('{"level": "critical", "event": "oom"}', "error") is True
    assert matches_level('{"level": "warning", "event": "warn"}', "error") is False
