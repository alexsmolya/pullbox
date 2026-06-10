"""Tests for import scan resume progress helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pullbox.models.import_job import ImportJobStatus

if TYPE_CHECKING:
    from pullbox.schemas.import_job import ImportProgressEvent


@pytest.mark.asyncio
async def test_emit_scan_resume_progress_builds_event_and_delays() -> None:
    from pullbox.services.import_scan_resume_progress import emit_scan_resume_progress

    job = SimpleNamespace(id=12, scan_started_at=datetime.now(UTC))
    session = object()
    observed_events: list[ImportProgressEvent] = []
    delayed = False

    async def emit_progress(
        _session: object,
        _job: object,
        event: ImportProgressEvent,
        progress_callback=None,
    ) -> None:
        observed_events.append(event)
        if progress_callback is not None:
            await progress_callback(event)

    async def progress_callback(_event: ImportProgressEvent) -> None:
        return None

    async def maybe_slow_phase_delay() -> None:
        nonlocal delayed
        delayed = True

    await emit_scan_resume_progress(
        session,
        job,
        status=ImportJobStatus.MATCHING,
        phase="matching",
        progress=50,
        message="Resuming ComicVine matching...",
        estimate_remaining_seconds=lambda started_at, progress: 42,
        job_stats=lambda _job: {"series_found": 3},
        emit_progress=emit_progress,
        maybe_slow_phase_delay=maybe_slow_phase_delay,
        progress_callback=progress_callback,
    )

    assert delayed is True
    assert len(observed_events) == 1
    event = observed_events[0]
    assert event.job_id == 12
    assert event.status == ImportJobStatus.MATCHING
    assert event.phase == "matching"
    assert event.progress == 50
    assert event.message == "Resuming ComicVine matching..."
    assert event.estimated_seconds_remaining == 42
    assert event.series_found == 3


@pytest.mark.asyncio
async def test_emit_scan_resume_progress_noops_without_callback() -> None:
    from pullbox.services.import_scan_resume_progress import emit_scan_resume_progress

    called = False

    async def emit_progress(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    async def maybe_slow_phase_delay() -> None:
        nonlocal called
        called = True

    await emit_scan_resume_progress(
        object(),
        SimpleNamespace(id=1, scan_started_at=None),
        status=ImportJobStatus.ANALYZING,
        phase="analyzing",
        progress=25,
        message="Resuming duplicate analysis...",
        estimate_remaining_seconds=lambda _started_at, _progress: None,
        job_stats=lambda _job: {},
        emit_progress=emit_progress,
        maybe_slow_phase_delay=maybe_slow_phase_delay,
        progress_callback=None,
    )

    assert called is False
