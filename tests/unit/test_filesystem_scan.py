"""Tests for deterministic recursive filesystem scans."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pullbox.core.filesystem_scan import iter_supported_files

if TYPE_CHECKING:
    from pathlib import Path


class TestIterSupportedFiles:
    """Verify recursive scan behavior stays deterministic and resilient."""

    def test_recurses_in_sorted_order(self, tmp_path: Path) -> None:
        root_file = tmp_path / "B_root.CBZ"
        root_file.write_text("root")

        nested_dir = tmp_path / "A Series"
        nested_dir.mkdir()
        nested_file = nested_dir / "Issue 002.cbz"
        nested_file.write_text("nested")

        deep_dir = nested_dir / "Annuals"
        deep_dir.mkdir()
        deep_file = deep_dir / "Issue 001.cbz"
        deep_file.write_text("deep")

        ignored = tmp_path / "Z Misc" / "notes.txt"
        ignored.parent.mkdir()
        ignored.write_text("ignore")

        results = list(iter_supported_files(tmp_path, frozenset({".cbz"})))

        assert results == [root_file, nested_file, deep_file]

    def test_nonexistent_root_yields_empty(self, tmp_path: Path) -> None:
        results = list(iter_supported_files(tmp_path / "missing", frozenset({".cbz"})))
        assert results == []

    def test_logs_walk_errors_and_continues(self, tmp_path: Path, monkeypatch) -> None:
        warnings: list[dict[str, str | None]] = []

        from pullbox.core import filesystem_scan as fs_mod

        def fake_warning(event: str, **kwargs: str | None) -> None:
            warnings.append({"event": event, **kwargs})

        def fake_walk(
            root: Path,
            onerror,
        ):
            onerror(PermissionError(13, "Permission denied", os.fspath(root / "secret")))
            yield (os.fspath(root), [], ["visible.cbz", "ignore.txt"])

        monkeypatch.setattr(fs_mod.logger, "warning", fake_warning)
        monkeypatch.setattr(fs_mod.os, "walk", fake_walk)

        root = tmp_path
        results = list(iter_supported_files(root, frozenset({".cbz"})))

        assert results == [root / "visible.cbz"]
        assert warnings == [
            {
                "event": "filesystem_scan_walk_error",
                "root": str(root),
                "path": str(root / "secret"),
                "error": f"[Errno 13] Permission denied: '{root / 'secret'}'",
            }
        ]
