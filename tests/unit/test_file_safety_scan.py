"""Tests for recursive file-safety directory scanning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.core.file_safety import scan_directory_for_dangerous_files

if TYPE_CHECKING:
    from pathlib import Path


class TestScanDirectoryForDangerousFiles:
    """Verify dangerous file discovery is recursive and deterministic."""

    def test_recurses_in_sorted_order(self, tmp_path: Path) -> None:
        root_file = tmp_path / "B_root.exe"
        root_file.write_text("root")

        nested_dir = tmp_path / "A Scripts"
        nested_dir.mkdir()
        nested_file = nested_dir / "Issue 002.ps1"
        nested_file.write_text("nested")

        deep_dir = nested_dir / "Annuals"
        deep_dir.mkdir()
        deep_file = deep_dir / "Issue 001.bat"
        deep_file.write_text("deep")

        ignored = tmp_path / "docs" / "readme.txt"
        ignored.parent.mkdir()
        ignored.write_text("safe")

        dangerous = scan_directory_for_dangerous_files(tmp_path)

        assert dangerous == [root_file, nested_file, deep_file]

    def test_nonexistent_root_returns_empty(self, tmp_path: Path) -> None:
        dangerous = scan_directory_for_dangerous_files(tmp_path / "missing")
        assert dangerous == []
