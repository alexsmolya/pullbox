"""Archive reader for comic book files (CBZ, CBR, CB7, CBT).

Provides a unified interface for reading comic book archives regardless
of underlying format.  Auto-detects the format from the file extension.
All archive operations run synchronously — callers should use a thread
pool executor for CPU-bound work.
"""

from __future__ import annotations

import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import structlog

from pullbox.core.comicinfo import ComicInfoData, parse_comicinfo
from pullbox.core.rar_backend import RarBackendUnavailableError, configure_rarfile_backend

logger = structlog.get_logger(__name__)
_ARCHIVE_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"})


class ArchiveError(Exception):
    """Raised when an archive cannot be read or is corrupt."""


class ArchiveReader:
    """Unified reader for CBZ, CBR, CB7, and CBT comic archives.

    Args:
        path: Path to the archive file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._extension = path.suffix.lower()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def format(self) -> str:
        """Return the archive format based on file extension."""
        return self._extension.lstrip(".")

    def list_files(self) -> list[str]:
        """List all files in the archive."""
        log = logger.bind(path=str(self._path), format=self.format)
        log.debug("archive_list_files")

        try:
            if self._extension == ".cbz":
                return self._list_zip()
            if self._extension == ".cbr":
                return self._list_rar()
            if self._extension == ".cb7":
                return self._list_7z()
            if self._extension == ".cbt":
                return self._list_tar()
        except ArchiveError:
            raise
        except Exception as exc:
            log.error("archive_list_failed", error=str(exc))
            raise ArchiveError(f"Failed to list archive: {exc}") from exc

        raise ArchiveError(f"Unsupported format: {self._extension}")

    def read_file(self, name: str) -> bytes:
        """Read a specific file from the archive by name."""
        log = logger.bind(path=str(self._path), file=name)
        log.debug("archive_read_file")

        try:
            if self._extension == ".cbz":
                return self._read_zip(name)
            if self._extension == ".cbr":
                return self._read_rar(name)
            if self._extension == ".cb7":
                return self._read_7z(name)
            if self._extension == ".cbt":
                return self._read_tar(name)
        except ArchiveError:
            raise
        except Exception as exc:
            log.error("archive_read_failed", error=str(exc), file=name)
            raise ArchiveError(f"Failed to read '{name}': {exc}") from exc

        raise ArchiveError(f"Unsupported format: {self._extension}")

    def read_comicinfo(self) -> ComicInfoData | None:
        """Extract and parse ComicInfo.xml from the archive.

        Returns ``None`` if the archive does not contain a ComicInfo.xml.
        """
        files = self.list_files()

        # ComicInfo.xml can be at root or in a subdirectory
        comicinfo_name = None
        for name in files:
            if name.lower().endswith("comicinfo.xml"):
                comicinfo_name = name
                break

        if comicinfo_name is None:
            return None

        xml_bytes = self.read_file(comicinfo_name)
        return parse_comicinfo(xml_bytes.decode("utf-8", errors="replace"))

    # -- CBZ (ZIP) ----------------------------------------------------------

    def _list_zip(self) -> list[str]:
        try:
            with zipfile.ZipFile(self._path, "r") as zf:
                return zf.namelist()
        except zipfile.BadZipFile as exc:
            raise ArchiveError(f"Corrupt CBZ file: {exc}") from exc

    def _read_zip(self, name: str) -> bytes:
        try:
            with zipfile.ZipFile(self._path, "r") as zf:
                return zf.read(name)
        except zipfile.BadZipFile as exc:
            raise ArchiveError(f"Corrupt CBZ file: {exc}") from exc
        except KeyError:
            raise ArchiveError(f"File not found in archive: {name}") from None

    # -- CBR (RAR) ----------------------------------------------------------

    def _list_rar(self) -> list[str]:
        try:
            import rarfile  # type: ignore[import-untyped]
        except ImportError:
            raise ArchiveError("rarfile package required for CBR support") from None

        try:
            configure_rarfile_backend()
            with rarfile.RarFile(self._path, "r") as rf:
                return list(rf.namelist())
        except RarBackendUnavailableError as exc:
            raise ArchiveError(str(exc)) from exc
        except rarfile.BadRarFile as exc:
            raise ArchiveError(f"Corrupt CBR file: {exc}") from exc

    def _read_rar(self, name: str) -> bytes:
        try:
            import rarfile
        except ImportError:
            raise ArchiveError("rarfile package required for CBR support") from None

        try:
            configure_rarfile_backend()
            with rarfile.RarFile(self._path, "r") as rf:
                return bytes(rf.read(name))
        except RarBackendUnavailableError as exc:
            raise ArchiveError(str(exc)) from exc
        except rarfile.BadRarFile as exc:
            raise ArchiveError(f"Corrupt CBR file: {exc}") from exc
        except KeyError:
            raise ArchiveError(f"File not found in archive: {name}") from None

    # -- CB7 (7z) -----------------------------------------------------------

    def _list_7z(self) -> list[str]:
        try:
            import py7zr
        except ImportError:
            raise ArchiveError("py7zr package required for CB7 support") from None

        try:
            with py7zr.SevenZipFile(self._path, "r") as sz:
                return list(sz.getnames())
        except py7zr.Bad7zFile as exc:
            raise ArchiveError(f"Corrupt CB7 file: {exc}") from exc

    def _read_7z(self, name: str) -> bytes:
        try:
            import py7zr
        except ImportError:
            raise ArchiveError("py7zr package required for CB7 support") from None

        try:
            _validate_archive_member_name(name)
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                with py7zr.SevenZipFile(self._path, "r") as sz:
                    sz.extract(path=temp_root, targets=[name])
                extracted = (temp_root / Path(name)).resolve(strict=False)
                if not extracted.is_relative_to(temp_root.resolve()) or not extracted.is_file():
                    raise ArchiveError(f"File not found in archive: {name}")
                return extracted.read_bytes()
        except py7zr.Bad7zFile as exc:
            raise ArchiveError(f"Corrupt CB7 file: {exc}") from exc

    # -- CBT (TAR) ----------------------------------------------------------

    def _list_tar(self) -> list[str]:
        try:
            with tarfile.open(self._path, "r:*") as archive:
                return [member.name for member in archive.getmembers()]
        except tarfile.TarError as exc:
            raise ArchiveError(f"Corrupt CBT file: {exc}") from exc

    def _read_tar(self, name: str) -> bytes:
        _validate_archive_member_name(name)
        try:
            with tarfile.open(self._path, "r:*") as archive:
                member = archive.getmember(name)
                if not member.isfile():
                    raise ArchiveError(f"File is not a regular archive member: {name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ArchiveError(f"File not found in archive: {name}")
                return extracted.read()
        except KeyError:
            raise ArchiveError(f"File not found in archive: {name}") from None
        except tarfile.TarError as exc:
            raise ArchiveError(f"Corrupt CBT file: {exc}") from exc


def _validate_archive_member_name(name: str) -> None:
    """Reject absolute and traversal archive member names before extraction."""
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if member.is_absolute() or not member.parts or ".." in member.parts:
        raise ArchiveError("Unsafe archive member path")


def inspect_archive_page_count(path: Path) -> int | None:
    """Return the number of image entries in an archive, excluding metadata files."""
    try:
        entries = ArchiveReader(path).list_files()
    except ArchiveError:
        return None

    page_count = 0
    for entry in entries:
        entry_path = Path(entry)
        if "__MACOSX" in entry_path.parts or entry_path.name.startswith("."):
            continue
        if entry_path.suffix.lower() in _ARCHIVE_IMAGE_SUFFIXES:
            page_count += 1
    return page_count or None
