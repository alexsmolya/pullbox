"""Background task for warming local series cover cache."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import case, select

from pullbox.core.scheduler import scheduled_task
from pullbox.database import get_session_factory
from pullbox.models.series import Series
from pullbox.services.cover_cache_service import cache_series_cover, resolve_series_cover_file

logger = structlog.get_logger(__name__)


@dataclass
class CoverBackfillStats:
    """Summary of one cover backfill run."""

    processed: int = 0
    downloaded: int = 0
    linked_existing: int = 0
    failed: int = 0


async def backfill_series_covers(limit: int | None = None) -> CoverBackfillStats:
    """Warm local series covers for records that still rely on remote URLs."""
    factory = get_session_factory()
    stats = CoverBackfillStats()

    async with factory() as session:
        query = (
            select(Series)
            .where(Series.cover_url.is_not(None))
            .order_by(
                case((Series.cover_path.is_(None), 0), else_=1),
                Series.created_at.desc(),
                Series.id.desc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)

        result = await session.execute(query)
        series_rows = list(result.scalars().all())

        for series in series_rows:
            stats.processed += 1
            try:
                existing_cover = await resolve_series_cover_file(session, series)
                if existing_cover:
                    api_cover_path = f"/api/v1/series/{series.id}/cover"
                    if series.cover_path != api_cover_path:
                        series.cover_path = api_cover_path
                        stats.linked_existing += 1
                    continue

                cached_cover = await cache_series_cover(session, series)
                if cached_cover:
                    stats.downloaded += 1
                else:
                    stats.failed += 1
            except Exception:
                stats.failed += 1
                logger.exception(
                    "series_cover_backfill_failed",
                    series_id=series.id,
                    title=series.title,
                )

        await session.commit()

    logger.info(
        "series_cover_backfill_complete",
        processed=stats.processed,
        downloaded=stats.downloaded,
        linked_existing=stats.linked_existing,
        failed=stats.failed,
        limit=limit,
    )
    return stats


@scheduled_task(
    task_id="backfill_series_covers",
    trigger="interval",
    display_name="Backfill Series Covers",
    hours=24,
)
async def scheduled_backfill_series_covers() -> None:
    """Periodically warm local cover cache for older series."""
    await backfill_series_covers()
