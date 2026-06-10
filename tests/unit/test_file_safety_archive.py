"""Archive safety contracts for import and post-processing boundaries."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from pullbox.core.file_safety import (
    FileSafetyError,
    check_archive_path_traversal,
    classify_resource_safety_exception,
    run_safety_checks,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_zip_path_traversal_detection_handles_posix_and_windows_entries(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "malicious.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.jpg", b"bad")
        zf.writestr(r"..\outside.jpg", b"bad")
        zf.writestr("/absolute.jpg", b"bad")
        zf.writestr(r"C:\absolute.jpg", b"bad")
        zf.writestr("safe/page.jpg", b"ok")

    assert check_archive_path_traversal(archive) == [
        "../outside.jpg",
        r"..\outside.jpg",
        "/absolute.jpg",
        r"C:\absolute.jpg",
    ]


def test_run_safety_checks_rejects_unreadable_zip_archive(tmp_path: Path) -> None:
    archive = tmp_path / "corrupt.cbz"
    archive.write_bytes(b"not a zip archive")

    with pytest.raises(FileSafetyError, match="Archive could not be inspected"):
        run_safety_checks(
            archive,
            block_dangerous=True,
            max_archive_size=2000 * 1024 * 1024,
        )


def test_run_safety_checks_inspects_zip_archive_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "safe.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe/page001.jpg", b"ok")
        zf.writestr("safe/page002.jpg", b"ok")

    open_count = 0
    original_zip_file = zipfile.ZipFile

    def counting_zip_file(*args: Any, **kwargs: Any) -> Any:
        nonlocal open_count
        open_count += 1
        return original_zip_file(*args, **kwargs)

    monkeypatch.setattr(zipfile, "ZipFile", counting_zip_file)

    run_safety_checks(
        archive,
        block_dangerous=True,
        max_archive_size=2000 * 1024 * 1024,
    )

    assert open_count == 1


def test_archive_size_error_is_overrideable_resource_safety_exception() -> None:
    block = classify_resource_safety_exception(
        FileSafetyError(
            "Archive decompressed size (4,248,234,210 bytes) exceeds limit (2,097,152,000 bytes)",
            details=["/imports/Dark Nights Death Metal Omnibus.cbz"],
        )
    )

    assert block is not None
    assert block.kind == "archive_decompressed_size"
    assert block.overrideable is True
    assert block.details == ["/imports/Dark Nights Death Metal Omnibus.cbz"]


def test_non_resource_safety_errors_are_not_overrideable() -> None:
    traversal = classify_resource_safety_exception(
        FileSafetyError(
            "Archive contains path traversal entries — entire release rejected",
            details=["../outside.jpg"],
        )
    )
    dangerous = classify_resource_safety_exception(
        FileSafetyError(
            "Archive contains 1 dangerous file(s) — entire release rejected",
            details=["setup.exe"],
        )
    )

    assert traversal is None
    assert dangerous is None


def test_pillow_decompression_bomb_error_is_overrideable_resource_exception() -> None:
    block = classify_resource_safety_exception(
        RuntimeError(
            "Archive worker failed during convert: DecompressionBombError: "
            "Image size exceeds limit of 178956970 pixels"
        )
    )

    assert block is not None
    assert block.kind == "pillow_decompression_bomb"
    assert "safe image processing limit" in block.reason
