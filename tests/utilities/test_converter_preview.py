"""Tests for UT-1.3 — file converter preview endpoint.

Verifies preview returns correct file counts, sizes, lossless flags,
and handles edge cases (empty library, invalid combinations, missing files).

Run:
    pytest tests/utilities/test_converter_preview.py -v
"""

from __future__ import annotations

import zipfile
from pathlib import Path  # noqa: TC003

import py7zr

from pullbox.utilities.schemas import ConvertPreviewRequest, ConvertPreviewResponse

# ── Helpers ────────────────────────────────────────────────────


def _create_test_cb7(path: Path, page_count: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(path, "w") as archive:
        for i in range(page_count):
            tmp = path.parent / f"_tmp_page_{i}.jpg"
            tmp.write_bytes(b"\xff\xd8" + b"X" * 500)
            archive.write(tmp, f"page_{i:03d}.jpg")
            tmp.unlink()
    return path


def _create_test_cbz(path: Path, page_count: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(page_count):
            zf.writestr(f"page_{i:03d}.jpg", b"\xff\xd8" + b"X" * 500)
    return path


# ── Schema Tests ───────────────────────────────────────────────


class TestPreviewSchemas:
    """Verify preview request/response schemas."""

    def test_request_valid(self) -> None:
        req = ConvertPreviewRequest(
            source_format="cb7",
            target_format="cbz",
            scope="all",
        )
        assert req.source_format == "cb7"
        assert req.target_format == "cbz"

    def test_request_with_file_paths(self) -> None:
        req = ConvertPreviewRequest(
            source_format="cbr",
            target_format="cbz",
            scope="manual",
            file_paths=["/comics/a.cbr", "/comics/b.cbr"],
        )
        assert len(req.file_paths) == 2

    def test_response_structure(self) -> None:
        resp = ConvertPreviewResponse(
            source_format="cb7",
            target_format="cbz",
            total_count=10,
            total_size_bytes=52428800,
            lossless=True,
            files=[
                {"path": "/comics/a.cb7", "output_path": "/comics/a.cbz", "size_bytes": 5242880},
            ],
        )
        assert resp.total_count == 10
        assert resp.lossless is True


# ── Preview Logic ──────────────────────────────────────────────


class TestPreviewLogic:
    """Verify preview generation logic."""

    def test_preview_with_manual_files(self, tmp_path: Path) -> None:
        from pullbox.utilities.executors.file_converter import build_convert_preview

        source_dir = tmp_path / "comics"
        f1 = _create_test_cb7(source_dir / "batman_001.cb7")
        f2 = _create_test_cb7(source_dir / "batman_002.cb7")

        result = build_convert_preview(
            source_format="cb7",
            target_format="cbz",
            scope="manual",
            file_paths=[str(f1), str(f2)],
        )

        assert result.total_count == 2
        assert result.total_size_bytes > 0
        assert len(result.files) == 2
        assert result.lossless is True
        assert result.files[0].output_path.endswith(".cbz")
        assert result.files[1].output_path.endswith(".cbz")

    def test_preview_no_matching_files(self, tmp_path: Path) -> None:
        from pullbox.utilities.executors.file_converter import build_convert_preview

        result = build_convert_preview(
            source_format="cbr",
            target_format="cbz",
            scope="manual",
            file_paths=[],
        )

        assert result.total_count == 0
        assert result.files == []

    def test_preview_missing_files_excluded(self, tmp_path: Path) -> None:
        """Mix of existing and non-existing paths — only existing counted."""
        from pullbox.utilities.executors.file_converter import build_convert_preview

        f1 = _create_test_cb7(tmp_path / "exists.cb7")

        result = build_convert_preview(
            source_format="cb7",
            target_format="cbz",
            scope="manual",
            file_paths=[str(f1), "/nonexistent/ghost.cb7"],
        )

        assert result.total_count == 1
        assert len(result.files) == 1
        assert result.files[0].output_path.endswith(".cbz")

    def test_preview_reports_resolved_paths(self, tmp_path: Path) -> None:
        from pullbox.utilities.executors.file_converter import build_convert_preview

        source_dir = tmp_path / "comics"
        f1 = _create_test_cb7(source_dir / "batman_001.cb7")

        result = build_convert_preview(
            source_format="cb7",
            target_format="cbz",
            scope="manual",
            file_paths=[str(source_dir / ".." / "comics" / f1.name)],
        )

        assert result.total_count == 1
        assert result.files[0].path == str(f1.resolve())
        assert result.files[0].output_path == str(f1.resolve().with_suffix(".cbz"))

    def test_preview_truncated_at_100(self, tmp_path: Path) -> None:
        """Large file list truncated to 100 in response, total_count accurate."""
        from pullbox.utilities.executors.file_converter import build_convert_preview

        source_dir = tmp_path / "comics"
        paths = []
        for i in range(150):
            f = _create_test_cb7(source_dir / f"file_{i:03d}.cb7", page_count=1)
            paths.append(str(f))

        result = build_convert_preview(
            source_format="cb7",
            target_format="cbz",
            scope="manual",
            file_paths=paths,
        )

        assert result.total_count == 150
        assert len(result.files) <= 100

    def test_preview_cbr_to_cbz_is_lossless(self) -> None:
        from pullbox.utilities.executors.file_converter import build_convert_preview

        result = build_convert_preview(
            source_format="cbr",
            target_format="cbz",
            scope="manual",
            file_paths=[],
        )
        assert result.lossless is True

    def test_preview_pdf_to_cbz_is_not_lossless(self) -> None:
        from pullbox.utilities.executors.file_converter import build_convert_preview

        result = build_convert_preview(
            source_format="pdf",
            target_format="cbz",
            scope="manual",
            file_paths=[],
        )
        assert result.lossless is False

    def test_preview_repack_allowed(self) -> None:
        """CBZ→CBZ repack preview should not raise."""
        from pullbox.utilities.executors.file_converter import build_convert_preview

        result = build_convert_preview(
            source_format="cbz",
            target_format="cbz",
            scope="manual",
            file_paths=[],
        )
        assert result.lossless is True
        assert result.total_count == 0

    def test_preview_with_no_files_returns_empty(self, tmp_path: Path) -> None:
        """Manual scope with no file paths returns empty result."""
        from pullbox.utilities.executors.file_converter import build_convert_preview

        result = build_convert_preview(
            source_format="cb7",
            target_format="cbz",
            scope="manual",
            file_paths=[],
        )

        assert result.total_count == 0
