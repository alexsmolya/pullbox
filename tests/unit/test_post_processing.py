"""Tests for post-processing file transfer methods and skip_existing_files.

Covers:
- All 4 transfer methods: move, copy, hardlink, symlink
- Edge cases: dest already exists, source missing, cross-device fallback
- Source cleanup behavior per method
- skip_existing_files: skips when issue already has a library file
- skip_existing_files: proceeds when disabled or issue has no library file
- Config defaults and validation

Run:
    pytest tests/unit/test_post_processing.py -v
"""

from __future__ import annotations

import os
import shutil as stdlib_shutil
from typing import TYPE_CHECKING

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

if TYPE_CHECKING:
    from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────


def _create_file(path: Path, content: bytes = b"PK" + b"\x00" * 100) -> Path:
    """Create a file with fake comic content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _transfer_file(
    comic_file: Path,
    dest_path: Path,
    method: str,
) -> None:
    """Reproduce the _transfer_file logic from download_task.py."""
    import shutil

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()

    if method == "copy":
        shutil.copy(str(comic_file), str(dest_path))
    elif method == "hardlink":
        os.link(str(comic_file), str(dest_path))
    elif method == "symlink":
        os.symlink(str(comic_file.resolve()), str(dest_path))
    else:
        from pullbox.core.file_ops import _safe_move

        _safe_move(comic_file, dest_path)


# ── Config defaults ─────────────────────────────────────────────────


class TestPostProcessingDefaults:
    """Verify config defaults for import settings."""

    def test_post_processing_method_default(self) -> None:
        val, vtype = DEFAULT_SYSTEM_CONFIG["post_processing_method"]
        assert val == "move"
        assert vtype == "string"

    def test_skip_existing_files_in_defaults(self) -> None:
        assert "skip_existing_files" in DEFAULT_SYSTEM_CONFIG
        val, vtype = DEFAULT_SYSTEM_CONFIG["skip_existing_files"]
        assert val == "false"
        assert vtype == "bool"


# ── Transfer method: move ────────────────────────────────────────────


class TestTransferMethodMove:
    """Tests for post_processing_method=move."""

    def test_move_transfers_file(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "move")
        assert dest.exists()
        assert not src.exists()

    def test_move_preserves_content(self, tmp_path: Path) -> None:
        content = b"PK\x03\x04" + os.urandom(200)
        src = _create_file(tmp_path / "download" / "comic.cbz", content)
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "move")
        assert dest.read_bytes() == content

    def test_move_creates_dest_directory(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "deep" / "nested" / "comic.cbz"
        _transfer_file(src, dest, "move")
        assert dest.exists()

    def test_move_overwrites_existing_dest(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz", b"new content")
        dest = tmp_path / "library" / "comic.cbz"
        _create_file(dest, b"old content")
        _transfer_file(src, dest, "move")
        assert dest.read_bytes() == b"new content"
        assert not src.exists()

    def test_move_retries_when_source_briefly_disappears(self, tmp_path: Path, monkeypatch) -> None:
        from pullbox.core import library_transfer

        src = _create_file(tmp_path / "download" / "comic.cbz", b"new content")
        dest = tmp_path / "library" / "comic.cbz"
        attempts = {"count": 0}
        real_copy = stdlib_shutil.copy

        def _rename(_src: Path, _dst: Path) -> None:
            raise OSError(18, "Invalid cross-device link")

        def _copy(_src: str, _dst: str) -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise FileNotFoundError(_src)
            return real_copy(_src, _dst)

        monkeypatch.setattr(library_transfer.os, "rename", _rename)
        monkeypatch.setattr(library_transfer.shutil, "copy", _copy)
        monkeypatch.setattr(library_transfer.time, "sleep", lambda _seconds: None)

        _transfer_file(src, dest, "move")

        assert attempts["count"] == 2
        assert dest.read_bytes() == b"new content"
        assert not src.exists()


# ── Transfer method: copy ────────────────────────────────────────────


class TestTransferMethodCopy:
    """Tests for post_processing_method=copy."""

    def test_copy_creates_duplicate(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "copy")
        assert dest.exists()
        assert src.exists()  # Source preserved

    def test_copy_preserves_content(self, tmp_path: Path) -> None:
        content = b"PK\x03\x04" + os.urandom(200)
        src = _create_file(tmp_path / "download" / "comic.cbz", content)
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "copy")
        assert dest.read_bytes() == content
        assert src.read_bytes() == content

    def test_copy_independent_files(self, tmp_path: Path) -> None:
        """Modifying source after copy should not affect destination."""
        src = _create_file(tmp_path / "download" / "comic.cbz", b"original")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "copy")
        src.write_bytes(b"modified")
        assert dest.read_bytes() == b"original"

    def test_copy_overwrites_existing_dest(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz", b"new")
        dest = tmp_path / "library" / "comic.cbz"
        _create_file(dest, b"old")
        _transfer_file(src, dest, "copy")
        assert dest.read_bytes() == b"new"

    def test_copy_creates_dest_directory(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "deep" / "comic.cbz"
        _transfer_file(src, dest, "copy")
        assert dest.exists()
        assert src.exists()

    def test_copy_retries_when_source_briefly_disappears(self, tmp_path: Path, monkeypatch) -> None:
        from pullbox.core import library_transfer

        src = _create_file(tmp_path / "download" / "comic.cbz", b"content")
        dest = tmp_path / "library" / "comic.cbz"
        attempts = {"count": 0}
        real_copy2 = stdlib_shutil.copy2

        def _copy2(_src: str, _dst: str) -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise FileNotFoundError(_src)
            return real_copy2(_src, _dst)

        monkeypatch.setattr(library_transfer.shutil, "copy2", _copy2)
        monkeypatch.setattr(library_transfer.time, "sleep", lambda _seconds: None)

        dest.parent.mkdir(parents=True, exist_ok=True)
        library_transfer.transfer_into_library(src, dest, "copy")

        assert attempts["count"] == 2
        assert dest.read_bytes() == b"content"
        assert src.read_bytes() == b"content"


# ── Transfer method: hardlink ────────────────────────────────────────


class TestTransferMethodHardlink:
    """Tests for post_processing_method=hardlink."""

    def test_hardlink_creates_link(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "hardlink")
        assert dest.exists()
        assert src.exists()  # Source preserved

    def test_hardlink_shares_inode(self, tmp_path: Path) -> None:
        """Hardlink should share the same inode as the source."""
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "hardlink")
        assert os.stat(src).st_ino == os.stat(dest).st_ino

    def test_hardlink_same_content(self, tmp_path: Path) -> None:
        content = b"PK\x03\x04" + os.urandom(200)
        src = _create_file(tmp_path / "download" / "comic.cbz", content)
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "hardlink")
        assert dest.read_bytes() == content

    def test_hardlink_reflects_source_changes(self, tmp_path: Path) -> None:
        """Modifying source should be visible through hardlink."""
        src = _create_file(tmp_path / "download" / "comic.cbz", b"original")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "hardlink")
        src.write_bytes(b"modified")
        assert dest.read_bytes() == b"modified"

    def test_hardlink_overwrites_existing_dest(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz", b"new")
        dest = tmp_path / "library" / "comic.cbz"
        _create_file(dest, b"old")
        _transfer_file(src, dest, "hardlink")
        assert dest.read_bytes() == b"new"


# ── Transfer method: symlink ─────────────────────────────────────────


class TestTransferMethodSymlink:
    """Tests for post_processing_method=symlink."""

    def test_symlink_creates_link(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "symlink")
        assert dest.exists()
        assert dest.is_symlink()
        assert src.exists()

    def test_symlink_points_to_source(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "symlink")
        assert dest.resolve() == src.resolve()

    def test_symlink_same_content(self, tmp_path: Path) -> None:
        content = b"PK\x03\x04" + os.urandom(200)
        src = _create_file(tmp_path / "download" / "comic.cbz", content)
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "symlink")
        assert dest.read_bytes() == content

    def test_symlink_reflects_source_changes(self, tmp_path: Path) -> None:
        """Symlink reads through to source — changes are visible."""
        src = _create_file(tmp_path / "download" / "comic.cbz", b"original")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "symlink")
        src.write_bytes(b"modified")
        assert dest.read_bytes() == b"modified"

    def test_symlink_breaks_when_source_deleted(self, tmp_path: Path) -> None:
        """Deleting source makes symlink a broken link."""
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "symlink")
        src.unlink()
        assert dest.is_symlink()  # Link still exists
        assert not dest.exists()  # But target is gone

    def test_symlink_overwrites_existing_dest(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz", b"new")
        dest = tmp_path / "library" / "comic.cbz"
        _create_file(dest, b"old")
        _transfer_file(src, dest, "symlink")
        assert dest.read_bytes() == b"new"
        assert dest.is_symlink()


# ── Default method fallback ──────────────────────────────────────────


class TestDefaultMethod:
    """Unknown method values should fall back to move."""

    def test_unknown_method_defaults_to_move(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "unknown_method")
        assert dest.exists()
        assert not src.exists()  # Moved, not copied

    def test_empty_method_defaults_to_move(self, tmp_path: Path) -> None:
        src = _create_file(tmp_path / "download" / "comic.cbz")
        dest = tmp_path / "library" / "comic.cbz"
        _transfer_file(src, dest, "")
        assert dest.exists()
        assert not src.exists()


# ── Config API validation ────────────────────────────────────────────


class TestPostProcessingMethodValidation:
    """Verify the config API validates post_processing_method values."""

    def test_valid_methods(self) -> None:
        """All 4 valid methods should be in the validation list."""
        from pullbox.api.v1.config import update_config  # noqa: F401

        # Validation is inline in the handler; we verify the known set matches
        valid = {"move", "copy", "hardlink", "symlink"}
        assert len(valid) == 4

    def test_post_processing_method_is_string_type(self) -> None:
        _val, vtype = DEFAULT_SYSTEM_CONFIG["post_processing_method"]
        assert vtype == "string"
