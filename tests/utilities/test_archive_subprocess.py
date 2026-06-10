"""Tests for interruptible archive subprocess helpers used by Step 4 import."""

from __future__ import annotations

import asyncio
import json
import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from pullbox.core.exceptions import JobCancelledError, JobPausedError
from pullbox.utilities.executors.archive_subprocess import (
    _raise_worker_error,
    _run_archive_operation,
    convert_file_interruptible,
    embed_comicinfo_in_cbz_interruptible,
    materialize_cbz_with_comicinfo_interruptible,
)

if TYPE_CHECKING:
    from pathlib import Path


def _create_test_cbz(path: Path, *, include_comicinfo: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page_000.jpg", "FAKE_JPEG")
        if include_comicinfo:
            archive.writestr(
                "ComicInfo.xml",
                '<?xml version="1.0"?><ComicInfo><Series>Old</Series></ComicInfo>',
            )
    return path


def _create_test_cb7(path: Path) -> Path:
    import py7zr

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = path.parent / "page_000.jpg"
    payload.write_text("FAKE_JPEG")
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.write(payload, payload.name)
    payload.unlink()
    return path


@pytest.mark.asyncio
async def test_convert_file_interruptible_converts_cb7_to_cbz(tmp_path: Path) -> None:
    source = _create_test_cb7(tmp_path / "source" / "test.cb7")
    destination = tmp_path / "output"
    destination.mkdir()
    progress_events: list[tuple[str, int, int, str]] = []

    async def _capture_progress(stage: str, current: int, total: int, unit: str) -> None:
        progress_events.append((stage, current, total, unit))

    result = await convert_file_interruptible(
        source,
        "cbz",
        destination=destination,
        progress_callback=_capture_progress,
    )

    assert result.exists()
    assert result.suffix == ".cbz"
    with zipfile.ZipFile(result) as archive:
        assert "page_000.jpg" in archive.namelist()
    assert any(stage in {"extracting", "packing"} for stage, *_rest in progress_events)
    assert any(stage == "packing" for stage, *_rest in progress_events)
    assert not list(destination.glob("pullbox-archive-progress-*.json"))


@pytest.mark.asyncio
async def test_embed_comicinfo_in_cbz_interruptible_updates_archive(tmp_path: Path) -> None:
    cbz = _create_test_cbz(tmp_path / "target.cbz", include_comicinfo=True)
    progress_events: list[tuple[str, int, int, str]] = []

    async def _capture_progress(stage: str, current: int, total: int, unit: str) -> None:
        progress_events.append((stage, current, total, unit))

    changed = await embed_comicinfo_in_cbz_interruptible(
        cbz,
        {"Series": "Chicken Devil", "Number": "4"},
        progress_callback=_capture_progress,
    )

    assert changed is True
    with zipfile.ZipFile(cbz) as archive:
        content = archive.read("ComicInfo.xml").decode("utf-8")
    assert "Chicken Devil" in content
    assert "4" in content
    assert progress_events
    assert progress_events[-1][0] == "rewriting"
    assert progress_events[-1][1] == progress_events[-1][2]
    assert not list(tmp_path.glob("pullbox-archive-progress-*.json"))


@pytest.mark.asyncio
async def test_small_materialize_cbz_with_comicinfo_uses_inline_fast_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_test_cbz(tmp_path / "source.cbz", include_comicinfo=True)
    target = tmp_path / "library" / "target.cbz"
    progress_events: list[tuple[str, int, int, str]] = []

    async def fail_if_subprocess_starts(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("small CBZ materialization should not spawn a worker process")

    async def _capture_progress(stage: str, current: int, total: int, unit: str) -> None:
        progress_events.append((stage, current, total, unit))

    monkeypatch.setattr(
        "pullbox.utilities.executors.archive_subprocess.asyncio.create_subprocess_exec",
        fail_if_subprocess_starts,
    )

    changed = await materialize_cbz_with_comicinfo_interruptible(
        source,
        target,
        {"Series": "Fast Path", "Number": "7"},
        transfer_method="copy",
        progress_callback=_capture_progress,
    )

    assert changed is True
    assert source.exists()
    assert target.exists()
    with zipfile.ZipFile(target) as archive:
        content = archive.read("ComicInfo.xml").decode("utf-8")
    assert "Fast Path" in content
    assert "7" in content
    assert progress_events
    assert progress_events[-1][0] == "rewriting"
    assert progress_events[-1][1] == progress_events[-1][2]
    assert not list(target.parent.glob("pullbox-archive-progress-*.json"))


@pytest.mark.asyncio
async def test_materialize_cbz_with_comicinfo_threshold_zero_uses_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _create_test_cbz(tmp_path / "source.cbz", include_comicinfo=True)
    target = tmp_path / "library" / "target.cbz"
    subprocess_started = False

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b'{"changed": true}', b"")

    async def fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> FakeProcess:
        nonlocal subprocess_started
        subprocess_started = True
        return FakeProcess()

    monkeypatch.setattr(
        "pullbox.utilities.executors.archive_subprocess._INLINE_MATERIALIZE_MAX_BYTES",
        0,
        raising=False,
    )
    monkeypatch.setattr(
        "pullbox.utilities.executors.archive_subprocess.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    changed = await materialize_cbz_with_comicinfo_interruptible(
        source,
        target,
        {"Series": "Worker Path"},
        transfer_method="copy",
    )

    assert changed is True
    assert subprocess_started is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control_exc", "expected_exc"),
    [
        (JobCancelledError("cancelled"), JobCancelledError),
        (JobPausedError("paused"), JobPausedError),
    ],
)
async def test_archive_operation_terminates_worker_and_cleans_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_exc: Exception,
    expected_exc: type[Exception],
) -> None:
    partial = tmp_path / "partial.cbz"
    partial.write_bytes(b"partial")

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self._done = asyncio.Event()
            self.terminate_called = False
            self.kill_called = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await self._done.wait()
            return (b"{}", b"")

        def terminate(self) -> None:
            self.terminate_called = True
            self.returncode = 143
            self._done.set()

        def kill(self) -> None:
            self.kill_called = True
            self.returncode = 137
            self._done.set()

    fake_proc = FakeProcess()

    async def fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> FakeProcess:
        return fake_proc

    async def cancel_now() -> None:
        raise control_exc

    monkeypatch.setattr(
        "pullbox.utilities.executors.archive_subprocess.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(expected_exc):
        await _run_archive_operation(
            "convert",
            {"source": "/tmp/source.cb7", "target_path": str(partial)},
            cancellation_check=cancel_now,
            cleanup_paths=[partial],
        )

    assert fake_proc.terminate_called is True
    assert not partial.exists()


def test_raise_worker_error_reports_signal_kill() -> None:
    with pytest.raises(RuntimeError, match="signal 9"):
        _raise_worker_error(
            "convert",
            {"source": "/tmp/source.pdf"},
            b"",
            b"",
            returncode=137,
        )


def test_raise_worker_error_normalizes_corrupt_cbr_without_payload() -> None:
    details = {
        "type": "BadRarFile",
        "message": "Failed the read enough data: req=262144 got=29",
    }

    with pytest.raises(ValueError) as exc_info:
        _raise_worker_error(
            "convert",
            {
                "source": "/imports/test5/Alice in Leatherland 001.cbr",
                "target_format": "cbz",
                "target_path": "/tmp/output.cbz",
            },
            b"",
            json.dumps(details).encode("utf-8"),
            returncode=1,
        )

    message = str(exc_info.value)
    assert "CBR archive appears corrupt or incomplete" in message
    assert "Alice in Leatherland 001.cbr" in message
    assert "Try re-downloading or replacing the file" in message
    assert "payload=" not in message
