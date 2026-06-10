"""Provider-error handling helpers for import file matching."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.exceptions import ImportProviderDegradedError
    from pullbox.models.import_job import ImportedSeries

    LogEventFunc = Callable[..., Awaitable[None]]


async def defer_file_matching_for_provider_error(
    *,
    session: AsyncSession,
    job_id: int,
    imp_series: ImportedSeries,
    exc: ImportProviderDegradedError,
    log_event: LogEventFunc,
) -> None:
    """Mark a series as deferred when issue targets cannot be trusted."""
    imp_series.diagnostics = {
        "kind": "file_target_provider_error",
        "reason": "provider_degraded",
        "provider": exc.provider,
        "query": exc.query,
        "raw_year": exc.year,
        "attempts": exc.attempts,
        "last_error": exc.last_error,
    }
    await log_event(
        session,
        job_id,
        "WARNING",
        "import_file_matching_deferred_provider_error",
        message=(
            f"Deferred file matching for '{imp_series.raw_series_name}' because "
            "ComicVine issue targets were unavailable"
        ),
        raw_series_name=imp_series.raw_series_name,
        raw_year=imp_series.raw_year,
        provider=exc.provider,
        query=exc.query,
        attempts=exc.attempts,
        last_error=exc.last_error,
    )
