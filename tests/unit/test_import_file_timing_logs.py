"""Tests for import file timing log dispatch."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_log_import_file_timing_events_dispatches_known_timing_kinds() -> None:
    from pullbox.services.import_file_timing_logs import log_import_file_timing_events

    observed: list[tuple[str, str | None, dict[str, object]]] = []

    async def log_event(
        _session: object,
        _job_id: int,
        _level: str,
        event: str,
        message: str | None = None,
        **kwargs: object,
    ) -> None:
        observed.append((event, message, kwargs))

    await log_import_file_timing_events(
        object(),
        job_id=44,
        source_file_name="Issue 001.cbr",
        metadata_timing={"comicvine_issue_fetch_status": "cached"},
        operation_timings=[
            {
                "kind": "transfer",
                "duration_ms": 11,
                "target_file_name": "Issue 001.cbz",
            },
            {
                "kind": "cbz_comicinfo_materialize",
                "duration_ms": 22,
                "target_file_name": "Issue 001.cbz",
            },
            {
                "kind": "comicinfo_rewrite",
                "duration_ms": 33,
                "artifact_file_name": "Issue 001.cbz",
                "changed": True,
            },
            {"kind": "unknown", "duration_ms": 44},
        ],
        log_event=log_event,
    )

    assert [event for event, _message, _data in observed] == [
        "import_file_comicinfo_metadata_timed",
        "import_file_transfer_timed",
        "import_file_cbz_comicinfo_materialize_timed",
        "import_file_comicinfo_rewrite_timed",
    ]
    assert observed[0][1] == "ComicInfo metadata prepared: Issue 001.cbr"
    assert observed[0][2]["comicvine_issue_fetch_status"] == "cached"
    assert observed[1][1] == "File transfer completed in 11ms: Issue 001.cbz"
    assert observed[3][2]["changed"] is True
