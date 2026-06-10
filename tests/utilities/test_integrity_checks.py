"""Tests for standalone archive integrity checks."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest

from pullbox.utilities.executors import integrity_checks

if TYPE_CHECKING:
    from pathlib import Path


def _create_valid_cbz(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("page_001.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 500)
    return path


@pytest.mark.asyncio
async def test_check_file_integrity_is_available_from_archive_module(
    tmp_path: Path,
) -> None:
    result = await integrity_checks.check_file_integrity(_create_valid_cbz(tmp_path / "good.cbz"))

    assert isinstance(result, integrity_checks.IntegrityResult)
    assert result.status == "healthy"
    assert result.page_count == 1
    assert result.file_hash


@pytest.mark.asyncio
async def test_rar_backend_configuration_stays_mockable_in_archive_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rarfile

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

    result = await integrity_checks.check_file_integrity(cbr, deep=False)

    assert result.status == "healthy"
    assert result.page_count == 2
    assert backend_calls == [True]
