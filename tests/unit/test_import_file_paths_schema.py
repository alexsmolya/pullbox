"""Tests for ImportJobCreate file_paths field.

Verifies the schema accepts file_paths, validates paths exist,
and stores correctly.

Run:
    pytest tests/unit/test_import_file_paths_schema.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pullbox.schemas.import_job import ImportJobCreate


class TestFilePathsField:
    """ImportJobCreate accepts optional file_paths."""

    def test_file_paths_none_by_default(self, tmp_path: Path) -> None:
        """file_paths defaults to None."""
        source = tmp_path / "comics"
        source.mkdir()
        job = ImportJobCreate(
            source_path=str(source),
            source_type="filesystem",
        )
        assert job.file_paths is None

    def test_file_paths_accepted(self, tmp_path: Path) -> None:
        """file_paths is accepted when files exist."""
        f1 = tmp_path / "comic1.cbz"
        f2 = tmp_path / "comic2.cbz"
        f1.write_bytes(b"fake")
        f2.write_bytes(b"fake")

        job = ImportJobCreate(
            source_path=str(f1),
            file_paths=[str(f1), str(f2)],
            source_type="filesystem",
        )
        assert job.file_paths is not None
        assert len(job.file_paths) == 2

    def test_file_paths_validated(self, tmp_path: Path) -> None:
        """Nonexistent file in file_paths raises ValueError."""
        real = tmp_path / "real.cbz"
        real.write_bytes(b"fake")

        with pytest.raises(Exception, match="does not exist"):
            ImportJobCreate(
                source_path=str(real),
                file_paths=[str(real), str(tmp_path / "nonexistent.cbz")],
                source_type="filesystem",
            )

    def test_file_paths_resolved(self, tmp_path: Path) -> None:
        """file_paths are resolved to absolute paths."""
        f1 = tmp_path / "sub" / "comic.cbz"
        f1.parent.mkdir()
        f1.write_bytes(b"fake")

        job = ImportJobCreate(
            source_path=str(f1),
            file_paths=[str(f1)],
            source_type="filesystem",
        )
        assert job.file_paths is not None
        assert Path(job.file_paths[0]).is_absolute()

    def test_source_path_still_required(self, tmp_path: Path) -> None:
        """source_path is still required even with file_paths."""
        from pydantic import ValidationError

        f1 = tmp_path / "comic.cbz"
        f1.write_bytes(b"fake")

        with pytest.raises(ValidationError, match="source_path"):
            ImportJobCreate(
                file_paths=[str(f1)],
                source_type="filesystem",
            )
