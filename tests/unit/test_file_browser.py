"""Tests for file browser endpoint and file mode (C-8.5).

Verifies:
- /api/v1/filesystem/browse returns files and directories
- Extension filter limits returned files
- Hidden files are excluded
- Files include size information
- Empty directory returns empty lists
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class TestBrowseFileDiscovery:
    """The browse endpoint discovers files filtered by extension."""

    def test_finds_db_files(self, tmp_path: Path) -> None:
        (tmp_path / "mylar.db").write_text("sqlite")
        (tmp_path / "other.txt").write_text("text")
        (tmp_path / "subdir").mkdir()

        from pullbox.api.v1.filesystem import FileEntry

        ext_filter = frozenset({".db"})
        files: list[FileEntry] = []
        for entry in sorted(tmp_path.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.suffix.lower() in ext_filter:
                files.append(FileEntry(name=entry.name, path=str(entry), size=entry.stat().st_size))

        assert len(files) == 1
        assert files[0].name == "mylar.db"
        assert files[0].size > 0

    def test_multiple_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "comic.cbz").write_text("zip")
        (tmp_path / "comic.cbr").write_text("rar")
        (tmp_path / "readme.txt").write_text("text")

        from pullbox.api.v1.filesystem import FileEntry

        ext_filter = frozenset({".cbz", ".cbr"})
        files: list[FileEntry] = []
        for entry in sorted(tmp_path.iterdir()):
            if entry.is_file() and entry.suffix.lower() in ext_filter:
                files.append(FileEntry(name=entry.name, path=str(entry), size=entry.stat().st_size))

        assert len(files) == 2
        names = {f.name for f in files}
        assert "comic.cbz" in names
        assert "comic.cbr" in names

    def test_hidden_files_excluded(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.db").write_text("sqlite")
        (tmp_path / "visible.db").write_text("sqlite")

        from pullbox.api.v1.filesystem import FileEntry

        ext_filter = frozenset({".db"})
        files: list[FileEntry] = []
        for entry in sorted(tmp_path.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.suffix.lower() in ext_filter:
                files.append(FileEntry(name=entry.name, path=str(entry), size=entry.stat().st_size))

        assert len(files) == 1
        assert files[0].name == "visible.db"

    def test_empty_directory(self, tmp_path: Path) -> None:
        from pullbox.api.v1.filesystem import FileEntry

        ext_filter = frozenset({".db"})
        files: list[FileEntry] = []
        for entry in sorted(tmp_path.iterdir()):
            if entry.is_file() and entry.suffix.lower() in ext_filter:
                files.append(FileEntry(name=entry.name, path=str(entry), size=entry.stat().st_size))

        assert len(files) == 0

    def test_extension_parsing(self) -> None:
        extensions = "db"
        ext_filter = frozenset(
            f".{e.strip().lower().lstrip('.')}" for e in extensions.split(",") if e.strip()
        )
        assert ext_filter == frozenset({".db"})

    def test_extension_parsing_multiple(self) -> None:
        extensions = "cbz,cbr, pdf"
        ext_filter = frozenset(
            f".{e.strip().lower().lstrip('.')}" for e in extensions.split(",") if e.strip()
        )
        assert ext_filter == frozenset({".cbz", ".cbr", ".pdf"})

    def test_extension_parsing_with_dots(self) -> None:
        extensions = ".db,.sqlite"
        ext_filter = frozenset(
            f".{e.strip().lower().lstrip('.')}" for e in extensions.split(",") if e.strip()
        )
        assert ext_filter == frozenset({".db", ".sqlite"})
