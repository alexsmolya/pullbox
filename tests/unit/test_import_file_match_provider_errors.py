"""Tests for provider degraded handling during file matching."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.core.exceptions import ImportProviderDegradedError
from pullbox.models.import_job import ImportedSeries
from pullbox.services.import_file_match_provider_errors import (
    defer_file_matching_for_provider_error,
)


@pytest.mark.asyncio
async def test_defer_file_matching_for_provider_error_sets_diagnostics_and_logs() -> None:
    imp_series = ImportedSeries(raw_series_name="King Dracula", raw_year=2026)
    exc = ImportProviderDegradedError(
        provider="comicvine",
        query="King Dracula",
        year=2026,
        attempts=3,
        last_error="timeout",
    )
    session = object()
    log_calls: list[dict[str, Any]] = []

    async def log_event(*args: object, **kwargs: object) -> None:
        log_calls.append({"args": args, "kwargs": kwargs})

    await defer_file_matching_for_provider_error(
        session=session,
        job_id=42,
        imp_series=imp_series,
        exc=exc,
        log_event=log_event,
    )

    assert imp_series.diagnostics == {
        "kind": "file_target_provider_error",
        "reason": "provider_degraded",
        "provider": "comicvine",
        "query": "King Dracula",
        "raw_year": 2026,
        "attempts": 3,
        "last_error": "timeout",
    }
    assert log_calls == [
        {
            "args": (
                session,
                42,
                "WARNING",
                "import_file_matching_deferred_provider_error",
            ),
            "kwargs": {
                "message": (
                    "Deferred file matching for 'King Dracula' because "
                    "ComicVine issue targets were unavailable"
                ),
                "raw_series_name": "King Dracula",
                "raw_year": 2026,
                "provider": "comicvine",
                "query": "King Dracula",
                "attempts": 3,
                "last_error": "timeout",
            },
        }
    ]
