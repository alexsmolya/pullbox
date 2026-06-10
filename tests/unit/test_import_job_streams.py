"""Tests for import job SSE stream helpers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from pullbox.api.v1.import_job_streams import (
    HEARTBEAT_SSE_FRAME,
    build_initial_import_progress_sse,
    is_import_stream_terminal_status,
    iter_import_log_sse,
    iter_import_progress_sse,
    make_sse_streaming_response,
)
from pullbox.models.import_job import ImportJobStatus
from pullbox.utilities.sse import SSEEvent


def test_build_initial_import_progress_sse_formats_cached_snapshot() -> None:
    job = SimpleNamespace(
        status=ImportJobStatus.COMPLETED,
        progress_snapshot={
            "snapshot_version": 2,
            "status": ImportJobStatus.COMPLETED.value,
            "mode": "import",
            "phase": "done",
            "progress": 100,
            "message": "Done",
            "progress_revision": 5,
        },
    )

    frame, is_terminal = build_initial_import_progress_sse(42, job)

    assert is_terminal is True
    assert frame is not None
    assert "event: progress" in frame
    assert '"job_id": 42' in frame
    assert '"status": "completed"' in frame


def test_build_initial_import_progress_sse_ignores_missing_snapshot() -> None:
    frame, is_terminal = build_initial_import_progress_sse(
        42,
        SimpleNamespace(status=ImportJobStatus.SCANNING, progress_snapshot={}),
    )

    assert frame is None
    assert is_terminal is False


def test_terminal_status_helper_matches_import_stream_contract() -> None:
    assert is_import_stream_terminal_status("review")
    assert is_import_stream_terminal_status(ImportJobStatus.COMPLETED)
    assert not is_import_stream_terminal_status("scanning")


def test_sse_streaming_response_uses_event_stream_headers() -> None:
    async def _empty_stream():
        if False:
            yield ""

    response = make_sse_streaming_response(_empty_stream())

    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"


@pytest.mark.asyncio
async def test_iter_import_progress_sse_yields_initial_event_and_stops_when_terminal() -> None:
    frames = [
        frame
        async for frame in iter_import_progress_sse(
            42,
            initial_event="event: progress\ndata: {}\n\n",
            initial_is_terminal=True,
            subscribe_fn=_never_used_subscribe,
            timeout_seconds=0.01,
        )
    ]

    assert frames == ["event: progress\ndata: {}\n\n"]


@pytest.mark.asyncio
async def test_iter_import_progress_sse_yields_events_and_stops_on_terminal_status() -> None:
    event = SSEEvent(
        channel="import:42",
        event_type="progress",
        data={"status": ImportJobStatus.COMPLETED.value},
    )

    frames = [
        frame
        async for frame in iter_import_progress_sse(
            42,
            subscribe_fn=_subscribe_with(event),
            timeout_seconds=0.01,
        )
    ]

    assert frames == [event.format_sse()]


@pytest.mark.asyncio
async def test_iter_import_log_sse_filters_non_log_events() -> None:
    progress = SSEEvent(channel="import:42", event_type="progress", data={"status": "scanning"})
    log = SSEEvent(channel="import:42", event_type="log", data={"message": "placed"})

    frames = [
        frame
        async for frame in iter_import_log_sse(
            42,
            subscribe_fn=_subscribe_with(progress, log, None),
            timeout_seconds=0.01,
        )
    ]

    assert frames == [log.format_sse()]


@pytest.mark.asyncio
async def test_iter_import_log_sse_yields_heartbeat_on_timeout() -> None:
    generator = iter_import_log_sse(
        42,
        subscribe_fn=_subscribe_with(),
        timeout_seconds=0.01,
    )

    assert await anext(generator) == HEARTBEAT_SSE_FRAME
    await generator.aclose()


def _subscribe_with(*events: SSEEvent | None):
    @asynccontextmanager
    async def _subscribe(_channel: str):
        queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()
        for event in events:
            queue.put_nowait(event)
        yield queue

    return _subscribe


@asynccontextmanager
async def _never_used_subscribe(_channel: str):
    raise AssertionError("terminal initial event should not subscribe")
    yield asyncio.Queue()  # pragma: no cover
