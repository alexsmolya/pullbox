"""Tests for diagnostic log file collection helpers."""

from __future__ import annotations

from pullbox.services.diagnostic_log_collector import MAX_LOG_FILE_BYTES, collect_log_files


def test_collect_log_files_returns_empty_for_missing_or_empty_dirs(tmp_path) -> None:
    assert collect_log_files(tmp_path / "missing") == []

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    assert collect_log_files(logs_dir) == []


def test_collect_log_files_reads_recent_log_files_and_truncates_large_files(tmp_path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "pullbox.log").write_text("hello\n")
    (logs_dir / "readme.txt").write_text("skip me\n")
    (logs_dir / "large.log").write_bytes(b"x" * (MAX_LOG_FILE_BYTES + 1000))

    collected = collect_log_files(logs_dir)

    names = [name for name, _content in collected]
    assert names == ["large.log", "pullbox.log"]
    large_content = dict(collected)["large.log"]
    assert large_content.startswith(b"[... truncated ...]\n")
    assert len(large_content) <= MAX_LOG_FILE_BYTES + 100
