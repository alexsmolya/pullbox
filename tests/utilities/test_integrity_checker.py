"""Tests for UT-6.1 — file integrity checker executor.

Verifies standalone check_file_integrity() function and
IntegrityCheckerExecutor for quick and deep scans on CBZ/CB7 archives.

Run:
    pytest tests/utilities/test_integrity_checker.py -v
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import py7zr
import pytest

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.integrity_checker import (
    IntegrityCheckerExecutor,
    IntegrityResult,
    check_file_integrity,
)

# ── Helpers ────────────────────────────────────────────────────


def _valid_jpeg_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _create_valid_cbz(path: Path, page_count: int = 5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _valid_jpeg_bytes()
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(page_count):
            zf.writestr(f"page_{i:03d}.jpg", payload)
    return path


def _create_valid_cb7(path: Path, page_count: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _valid_jpeg_bytes()
    with py7zr.SevenZipFile(path, "w") as archive:
        for i in range(page_count):
            tmp = path.parent / f"_tmp_{i}.jpg"
            tmp.write_bytes(payload)
            archive.write(tmp, f"page_{i:03d}.jpg")
            tmp.unlink()
    return path


def _create_cbz_no_images(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "No images here")
        zf.writestr("thumbs.db", "fake")
    return path


def _create_valid_cbt(path: Path, page_count: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _valid_jpeg_bytes()
    with tarfile.open(path, "w") as archive:
        for i in range(page_count):
            info = tarfile.TarInfo(name=f"page_{i:03d}.jpg")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path


def _create_traversal_cbt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _valid_jpeg_bytes()
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(name="../escaped.jpg")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return path


# ── IntegrityResult ────────────────────────────────────────────


class TestIntegrityResult:
    """Verify IntegrityResult dataclass."""

    def test_healthy_result(self) -> None:
        result = IntegrityResult(status="healthy", page_count=32)
        assert result.status == "healthy"
        assert result.page_count == 32
        assert result.warnings == []
        assert result.errors == []

    def test_failed_result(self) -> None:
        result = IntegrityResult(
            status="corrupt",
            page_count=0,
            errors=["Corrupt archive header"],
        )
        assert result.status == "corrupt"
        assert len(result.errors) == 1


# ── Quick Scan (standalone function) ───────────────────────────


class TestQuickScan:
    """Verify check_file_integrity() quick scan mode."""

    @pytest.mark.asyncio
    async def test_valid_cbz_passes(self, tmp_path: Path) -> None:
        cbz = _create_valid_cbz(tmp_path / "good.cbz")
        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 5

    @pytest.mark.asyncio
    async def test_valid_cb7_passes(self, tmp_path: Path) -> None:
        cb7 = _create_valid_cb7(tmp_path / "good.cb7")
        result = await check_file_integrity(cb7, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 3

    @pytest.mark.asyncio
    async def test_valid_cbr_configures_rar_backend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import rarfile

        from pullbox.utilities.executors import integrity_checks

        cbr = tmp_path / "good.cbr"
        cbr.write_bytes(b"Rar!\x1a\x07\x00fake")
        backend_calls: list[bool] = []

        class FakeRarFile:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def __enter__(self) -> FakeRarFile:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def namelist(self) -> list[str]:
                return ["page_001.jpg", "page_002.jpg"]

        monkeypatch.setattr(
            integrity_checks,
            "configure_rarfile_backend",
            lambda: backend_calls.append(True),
        )
        monkeypatch.setattr(rarfile, "RarFile", FakeRarFile)

        result = await check_file_integrity(cbr, deep=False)

        assert result.status == "healthy"
        assert result.page_count == 2
        assert backend_calls == [True]

    @pytest.mark.asyncio
    async def test_valid_cbt_passes(self, tmp_path: Path) -> None:
        cbt = _create_valid_cbt(tmp_path / "good.cbt")
        result = await check_file_integrity(cbt, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 3

    @pytest.mark.asyncio
    async def test_zero_byte_file_fails(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.cbz"
        empty.write_bytes(b"")
        result = await check_file_integrity(empty, deep=False)
        assert result.status == "corrupt"
        assert any("empty" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_corrupt_archive_fails(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.cbz"
        corrupt.write_bytes(b"NOT_A_ZIP_FILE_AT_ALL")
        result = await check_file_integrity(corrupt, deep=False)
        assert result.status == "corrupt"

    @pytest.mark.asyncio
    async def test_nonexistent_file_fails(self, tmp_path: Path) -> None:
        result = await check_file_integrity(tmp_path / "ghost.cbz", deep=False)
        assert result.status == "corrupt"
        assert any("not found" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_no_images_fails(self, tmp_path: Path) -> None:
        cbz = _create_cbz_no_images(tmp_path / "no_images.cbz")
        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "corrupt"
        assert any("no images" in e.lower() or "no valid" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_single_image_passes(self, tmp_path: Path) -> None:
        cbz = _create_valid_cbz(tmp_path / "single.cbz", page_count=1)
        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 1


# ── Deep Scan ──────────────────────────────────────────────────


class TestDeepScan:
    """Verify check_file_integrity() deep scan mode."""

    @pytest.mark.asyncio
    async def test_deep_valid_cbz_passes(self, tmp_path: Path) -> None:
        """Deep scan with synthetic images may warn but still counts pages."""
        cbz = _create_valid_cbz(tmp_path / "good.cbz", page_count=3)
        result = await check_file_integrity(cbz, deep=True)
        # Synthetic test images may produce warnings from Pillow verify
        assert result.status in ("healthy", "warning")
        assert result.page_count == 3

    @pytest.mark.asyncio
    async def test_deep_truncated_image_fails(self, tmp_path: Path) -> None:
        """Image that can't be decoded should fail deep integrity scans."""
        path = tmp_path / "bad_image.cbz"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("page_000.jpg", b"\xff\xd8\xff")  # truncated JPEG
            zf.writestr("page_001.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 500)
        result = await check_file_integrity(path, deep=True)
        assert result.status == "corrupt"
        assert any("verification failed" in error.lower() for error in result.errors)

    @pytest.mark.asyncio
    async def test_deep_cbt_rejects_path_traversal_members(self, tmp_path: Path) -> None:
        cbt = _create_traversal_cbt(tmp_path / "unsafe.cbt")
        escaped = tmp_path / "escaped.jpg"

        result = await check_file_integrity(cbt, deep=True)

        assert result.status == "corrupt"
        assert any("unsafe archive member" in error.lower() for error in result.errors)
        assert not escaped.exists()


# ── Config Validation ──────────────────────────────────────────


class TestValidateConfig:
    """Verify config validation."""

    def test_valid_config(self) -> None:
        executor = IntegrityCheckerExecutor()
        errors = executor.validate_config({"scan_depth": "quick"})
        assert errors == []

    def test_invalid_scan_depth(self) -> None:
        executor = IntegrityCheckerExecutor()
        errors = executor.validate_config({"scan_depth": "turbo"})
        assert any("scan_depth" in e.lower() for e in errors)


class TestGenerateItems:
    """Verify folder and manual scope item discovery."""

    @pytest.mark.asyncio
    async def test_folder_scope_recurses_into_nested_subfolders(self, tmp_path: Path) -> None:
        root_file = _create_valid_cbz(tmp_path / "root.cbz")
        nested_file = _create_valid_cbz(tmp_path / "series" / "nested.cbz")
        deep_file = _create_valid_cbz(tmp_path / "series" / "annuals" / "deep.cbz")
        ignored = tmp_path / "ignored" / "note.txt"
        ignored.parent.mkdir(parents=True, exist_ok=True)
        ignored.write_text("not a comic archive")

        executor = IntegrityCheckerExecutor()
        items = await executor.generate_items(
            {
                "scope": "folder",
                "scan_folder": str(tmp_path),
            }
        )

        assert [item["file_path"] for item in items] == [
            str(root_file),
            str(nested_file),
            str(deep_file),
        ]

    @pytest.mark.asyncio
    async def test_folder_scope_accepts_multiple_scan_folders(self, tmp_path: Path) -> None:
        folder_one = tmp_path / "Batman (2016)"
        folder_two = tmp_path / "Saga (2012)"
        file_one = _create_valid_cbz(folder_one / "batman-001.cbz")
        file_two = _create_valid_cbz(folder_two / "saga-001.cbz")

        executor = IntegrityCheckerExecutor()
        items = await executor.generate_items(
            {
                "scope": "folder",
                "scan_folders": [str(folder_one), str(folder_two)],
            }
        )

        assert [item["file_path"] for item in items] == [
            str(file_one),
            str(file_two),
        ]


# ── Process Item ───────────────────────────────────────────────


class TestProcessItem:
    """Verify executor process_item wraps standalone function."""

    def test_healthy_file(self, tmp_path: Path) -> None:
        cbz = _create_valid_cbz(tmp_path / "healthy.cbz")
        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={"id": "item-001", "file_path": str(cbz), "operation": "check"},
            job_config={"scan_depth": "quick"},
        )
        assert result.result == ItemResult.COMPLETED
        assert result.after_state.get("status") == "healthy"

    def test_corrupt_file(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.cbz"
        corrupt.write_bytes(b"GARBAGE")
        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={"id": "item-002", "file_path": str(corrupt), "operation": "check"},
            job_config={"scan_depth": "quick"},
        )
        assert result.result == ItemResult.FAILED
        assert result.after_state.get("status") == "corrupt"

    def test_missing_file(self, tmp_path: Path) -> None:
        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-003",
                "file_path": str(tmp_path / "nope.cbz"),
                "operation": "check",
            },
            job_config={"scan_depth": "quick"},
        )
        assert result.result == ItemResult.FAILED

    def test_corrupt_file_can_be_quarantined(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "bad.cbz"
        corrupt.write_bytes(b"GARBAGE")
        trash_dir = tmp_path / ".trash"

        executor = IntegrityCheckerExecutor()
        result = executor.process_item(
            item_data={"id": "item-004", "file_path": str(corrupt), "operation": "check"},
            job_config={
                "scan_depth": "quick",
                "corrupt_action": "quarantine",
                "trash_folder": str(trash_dir),
            },
        )

        assert result.result == ItemResult.COMPLETED
        assert result.before_state.get("path") == str(corrupt)
        assert result.after_state.get("status") == "corrupt"
        assert result.after_state.get("action") == "quarantine"
        assert Path(result.after_state["trash_path"]).exists()
        assert not corrupt.exists()


# ── Rollback ───────────────────────────────────────────────────


class TestRollback:
    """Verify rollback resets integrity flags."""

    def test_rollback_returns_completed(self) -> None:
        executor = IntegrityCheckerExecutor()
        result = executor.rollback_item(
            item_data={"id": "rb-001"},
            job_config={},
        )
        assert result.result == ItemResult.COMPLETED

    def test_rollback_restores_quarantined_file(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "restore-me.cbz"
        original_bytes = b"GARBAGE"
        corrupt.write_bytes(original_bytes)
        trash_dir = tmp_path / ".trash"

        executor = IntegrityCheckerExecutor()
        processed = executor.process_item(
            item_data={"id": "rb-002", "file_path": str(corrupt), "operation": "check"},
            job_config={
                "scan_depth": "quick",
                "corrupt_action": "quarantine",
                "trash_folder": str(trash_dir),
            },
        )

        result = executor.rollback_item(
            item_data={
                "id": "rb-002",
                "before_state": processed.before_state,
                "after_state": processed.after_state,
            },
            job_config={},
        )

        assert result.result == ItemResult.COMPLETED
        assert corrupt.exists()
        assert corrupt.read_bytes() == original_bytes


# ── Standalone Import ──────────────────────────────────────────


class TestStandaloneImport:
    """Verify the standalone function is importable (cross-sprint constraint)."""

    def test_importable(self) -> None:
        from pullbox.utilities.executors.integrity_checker import check_file_integrity

        assert callable(check_file_integrity)


# ── Integrity Edge Cases ──────────────────────────────────────


class TestIntegrityEdgeCases:
    """Verify edge cases in integrity checking."""

    @pytest.mark.asyncio
    async def test_permission_error_on_read(self, tmp_path: Path) -> None:
        """File exists but not readable returns corrupt with error message."""
        import os
        import sys

        if sys.platform == "win32":
            pytest.skip("chmod not effective on Windows")

        unreadable = tmp_path / "locked.cbz"
        _create_valid_cbz(unreadable, page_count=3)
        os.chmod(unreadable, 0o000)

        try:
            result = await check_file_integrity(unreadable, deep=False)
            assert result.status == "corrupt"
            assert len(result.errors) >= 1
        finally:
            os.chmod(unreadable, 0o644)

    @pytest.mark.asyncio
    async def test_archive_with_mixed_image_formats(self, tmp_path: Path) -> None:
        """CBZ with .jpg, .png, .gif all counted as pages."""
        cbz = tmp_path / "mixed_images.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            zf.writestr("cover.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 500)
            zf.writestr("page_001.png", b"\x89PNG" + b"\x00" * 500)
            zf.writestr("page_002.gif", b"GIF89a" + b"\x00" * 500)

        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 3

    @pytest.mark.asyncio
    async def test_single_image_archive_passes(self, tmp_path: Path) -> None:
        """Archive with exactly one image is healthy."""
        cbz = _create_valid_cbz(tmp_path / "single.cbz", page_count=1)
        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 1

    @pytest.mark.asyncio
    async def test_cbz_with_comicinfo_not_counted_as_image(self, tmp_path: Path) -> None:
        """ComicInfo.xml doesn't inflate page_count."""
        cbz = tmp_path / "with_ci.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            for i in range(5):
                zf.writestr(f"page_{i:03d}.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 500)
            zf.writestr(
                "ComicInfo.xml",
                '<?xml version="1.0"?><ComicInfo><Series>Test</Series></ComicInfo>',
            )

        result = await check_file_integrity(cbz, deep=False)
        assert result.status == "healthy"
        assert result.page_count == 5  # ComicInfo.xml NOT counted
