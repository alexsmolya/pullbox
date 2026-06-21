"""Tests for system log file API helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.responses import FileResponse, StreamingResponse

from pullbox.api.v1 import system_log_routes
from pullbox.api.v1.system_logs import (
    build_log_download_response,
    build_log_stream_response,
    clear_log_paths,
    delete_log_path,
    is_valid_log_path,
    iter_log_stream_events,
    list_log_file_responses,
    matches_level,
    read_log_content,
    validate_safe_filename,
)
from pullbox.core.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def test_list_log_file_responses_returns_log_files_newest_first(tmp_path: Path) -> None:
    old_log = tmp_path / "pullbox.log.1"
    old_log.write_text("old\n", encoding="utf-8")
    new_log = tmp_path / "pullbox.log"
    new_log.write_text("new\n", encoding="utf-8")
    os.utime(old_log, (1_700_000_000, 1_700_000_000))
    os.utime(new_log, (1_700_000_000, 1_700_000_000))
    ignored = tmp_path / "pullbox.txt"
    ignored.write_text("ignored\n", encoding="utf-8")

    rows = list_log_file_responses(tmp_path)

    assert [row.filename for row in rows] == ["pullbox.log", "pullbox.log.1"]
    assert rows[0].size_bytes == 4


def test_list_log_file_responses_handles_missing_directory_and_skips_directories(
    tmp_path: Path,
) -> None:
    assert list_log_file_responses(tmp_path / "missing") == []

    (tmp_path / "folder.log").mkdir()
    (tmp_path / "pullbox.log").write_text("real\n", encoding="utf-8")

    rows = list_log_file_responses(tmp_path)

    assert [row.filename for row in rows] == ["pullbox.log"]


def test_read_log_content_returns_tail_and_truncation_flag(tmp_path: Path) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    response = read_log_content(tmp_path, "pullbox.log", tail=2)

    assert response.filename == "pullbox.log"
    assert response.total_lines == 3
    assert response.lines == ["two", "three"]
    assert response.truncated is True


def test_clear_log_paths_deletes_only_log_files(tmp_path: Path) -> None:
    (tmp_path / "pullbox.log").write_text("one\n", encoding="utf-8")
    (tmp_path / "pullbox.log.1").write_text("two\n", encoding="utf-8")
    keep = tmp_path / "notes.txt"
    keep.write_text("keep\n", encoding="utf-8")

    response = clear_log_paths(tmp_path)

    assert response == {"message": "Cleared 2 log files."}
    assert keep.exists()
    assert not (tmp_path / "pullbox.log").exists()
    assert not (tmp_path / "pullbox.log.1").exists()


def test_matches_level_keeps_error_filter_critical_compatibility() -> None:
    assert matches_level('{"level": "critical", "event": "oom"}', "error") is True
    assert matches_level('{"level": "warning", "event": "warn"}', "error") is False


def test_log_filename_and_path_validation_rejects_unsafe_values(tmp_path: Path) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("ok\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.log"
    outside.write_text("outside\n", encoding="utf-8")

    assert validate_safe_filename("pullbox.log") is True
    assert validate_safe_filename("") is False
    assert validate_safe_filename("../pullbox.log") is False
    assert validate_safe_filename("nested/pullbox.log") is False
    assert validate_safe_filename("x" * 256) is False
    assert validate_safe_filename("-starts-with-dash.log") is False

    assert is_valid_log_path(tmp_path, log_path) is True
    assert is_valid_log_path(tmp_path, outside) is False
    assert is_valid_log_path(tmp_path, tmp_path / "notes.txt") is False


def test_log_path_validation_handles_resolution_errors() -> None:
    class BadPath:
        def resolve(self) -> object:
            raise OSError("boom")

    assert is_valid_log_path(BadPath(), BadPath()) is False  # type: ignore[arg-type]


def test_download_delete_and_stream_response_helpers(tmp_path: Path) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("one\n", encoding="utf-8")

    download = build_log_download_response(tmp_path, "pullbox.log")
    assert isinstance(download, FileResponse)
    assert download.media_type == "text/plain"

    stream = build_log_stream_response(
        tmp_path,
        "pullbox.log",
        SimpleNamespace(is_disconnected=lambda: True),
        level="all",
    )
    assert isinstance(stream, StreamingResponse)
    assert stream.media_type == "text/event-stream"
    assert stream.headers["x-accel-buffering"] == "no"

    assert delete_log_path(tmp_path, "pullbox.log") == {"message": "Log file deleted: pullbox.log"}
    assert not log_path.exists()

    with pytest.raises(ValidationError):
        build_log_download_response(tmp_path, "../pullbox.log")
    with pytest.raises(NotFoundError):
        build_log_download_response(tmp_path, "missing.log")


def test_clear_log_paths_handles_missing_and_singular_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert clear_log_paths(missing) == {"message": "No log files to clear."}

    (tmp_path / "single.log").write_text("one\n", encoding="utf-8")
    assert clear_log_paths(tmp_path) == {"message": "Cleared 1 log file."}


def test_matches_level_supports_structured_and_bracketed_levels() -> None:
    assert matches_level("anything at all", "all") is True
    assert matches_level('{"level":"info","event":"ready"}', "info") is True
    assert matches_level("[warning] careful", "warning") is True
    assert matches_level("level=debug started", "debug") is True
    assert matches_level('{"level":"info","event":"ready"}', "debug") is False


@pytest.mark.asyncio
async def test_iter_log_stream_events_yields_existing_lines_and_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text(
        '{"level":"debug","event":"debug"}\n{"level":"info","event":"ready"}\n',
        encoding="utf-8",
    )
    disconnected_checks = [False, True]

    async def _sleep(_seconds: float) -> None:
        return None

    async def _is_disconnected() -> bool:
        return disconnected_checks.pop(0)

    monkeypatch.setattr("pullbox.api.v1.system_logs.asyncio.sleep", _sleep)

    events: list[str] = []
    async for event in iter_log_stream_events(
        log_path,
        SimpleNamespace(is_disconnected=_is_disconnected),
        level="info",
    ):
        events.append(event)

    assert events[0] == 'data: {"line": "{\\"level\\":\\"info\\",\\"event\\":\\"ready\\"}"}\n\n'
    assert events[1] == 'data: {"heartbeat": true}\n\n'


@pytest.mark.asyncio
async def test_iter_log_stream_events_yields_appended_matching_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("existing\n", encoding="utf-8")
    disconnected_checks = [False, True]

    async def _sleep(_seconds: float) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write('{"level":"error","event":"boom"}\nignored info\n')

    async def _is_disconnected() -> bool:
        return disconnected_checks.pop(0)

    monkeypatch.setattr("pullbox.api.v1.system_logs.asyncio.sleep", _sleep)

    events: list[str] = []
    async for event in iter_log_stream_events(
        log_path,
        SimpleNamespace(is_disconnected=_is_disconnected),
        level="error",
    ):
        events.append(event)

    assert events == ['data: {"line": "{\\"level\\":\\"error\\",\\"event\\":\\"boom\\"}"}\n\n']


@pytest.mark.asyncio
async def test_iter_log_stream_events_handles_missing_and_truncated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _sleep_missing(_seconds: float) -> None:
        return None

    missing_disconnects = [False, True]

    async def _missing_disconnected() -> bool:
        return missing_disconnects.pop(0)

    monkeypatch.setattr("pullbox.api.v1.system_logs.asyncio.sleep", _sleep_missing)

    missing_events: list[str] = []
    async for event in iter_log_stream_events(
        tmp_path / "missing.log",
        SimpleNamespace(is_disconnected=_missing_disconnected),
        level="all",
    ):
        missing_events.append(event)
    assert missing_events == []

    log_path = tmp_path / "rotating.log"
    log_path.write_text("long existing text\n", encoding="utf-8")
    truncate_disconnects = [False, True]

    async def _sleep_truncate(_seconds: float) -> None:
        log_path.write_text("new\n", encoding="utf-8")

    async def _truncate_disconnected() -> bool:
        return truncate_disconnects.pop(0)

    monkeypatch.setattr("pullbox.api.v1.system_logs.asyncio.sleep", _sleep_truncate)

    truncated_events: list[str] = []
    async for event in iter_log_stream_events(
        log_path,
        SimpleNamespace(is_disconnected=_truncate_disconnected),
        level="all",
    ):
        truncated_events.append(event)
    assert truncated_events == [
        'data: {"line": "long existing text"}\n\n',
        'data: {"line": "new"}\n\n',
    ]


@pytest.mark.asyncio
async def test_system_log_route_wrappers_use_runtime_log_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    log_path = tmp_path / "pullbox.log"
    log_path.write_text("one\ntwo\n", encoding="utf-8")

    async def _logs_dir(_session: AsyncSession) -> Path:
        return tmp_path

    monkeypatch.setattr(system_log_routes, "_get_logs_dir", _logs_dir)

    listed = await system_log_routes.list_log_files(object(), db_session)  # type: ignore[arg-type]
    content = await system_log_routes.view_log_file(
        "pullbox.log",
        object(),  # type: ignore[arg-type]
        db_session,
        tail=1,
    )
    download = await system_log_routes.download_log_file(
        "pullbox.log",
        object(),  # type: ignore[arg-type]
        db_session,
    )
    stream = await system_log_routes.stream_log_file(
        "pullbox.log",
        SimpleNamespace(is_disconnected=lambda: True),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        db_session,
        level="all",
    )
    delete_response = await system_log_routes.delete_log_file(
        "pullbox.log",
        object(),  # type: ignore[arg-type]
        db_session,
    )
    (tmp_path / "second.log").write_text("again\n", encoding="utf-8")
    clear_response = await system_log_routes.clear_log_files(
        object(),  # type: ignore[arg-type]
        db_session,
    )

    assert [row.filename for row in listed] == ["pullbox.log"]
    assert content.lines == ["two"]
    assert isinstance(download, FileResponse)
    assert isinstance(stream, StreamingResponse)
    assert delete_response == {"message": "Log file deleted: pullbox.log"}
    assert clear_response == {"message": "Cleared 1 log file."}


@pytest.mark.asyncio
async def test_system_log_route_runtime_directory_uses_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(
        system_log_routes,
        "get_settings",
        lambda: SimpleNamespace(logs_dir=tmp_path),
    )

    assert await system_log_routes._get_logs_dir(db_session) == tmp_path
