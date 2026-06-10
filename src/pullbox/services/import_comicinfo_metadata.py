"""ComicInfo metadata enrichment helpers for import workflows."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from pullbox.models.creator import IssueCreator
from pullbox.models.issue import Issue

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def issue_needs_comicinfo_enrichment(
    session: AsyncSession,
    issue: Issue,
) -> bool:
    """Return true when full issue metadata could improve ComicInfo output."""
    if not issue.description or not issue.comicvine_url or issue.release_date is None:
        return True
    if issue.id is None:
        return False

    creator_count = (
        await session.execute(
            sa_select(sa_func.count())
            .select_from(IssueCreator)
            .where(IssueCreator.issue_id == issue.id)
        )
    ).scalar_one()
    return int(creator_count or 0) == 0


async def enrich_issue_for_comicinfo(
    session: AsyncSession,
    issue: Issue,
    *,
    metadata_service: Any,
    timing: dict[str, Any] | None = None,
    log_warning: Callable[..., Any] = logger.warning,
    time_monotonic: Callable[[], float] = time.monotonic,
) -> Issue:
    """Fetch full issue metadata once when ComicInfo needs authoritative fields."""
    if issue.comicvine_id is None or metadata_service is None:
        if timing is not None:
            timing["comicvine_issue_fetch_status"] = "skipped"
        return issue
    if not await issue_needs_comicinfo_enrichment(session, issue):
        if timing is not None:
            timing["comicvine_issue_fetch_status"] = "cached"
        return issue

    fetch_issue = getattr(metadata_service, "fetch_issue", None)
    if not callable(fetch_issue):
        if timing is not None:
            timing["comicvine_issue_fetch_status"] = "unavailable"
        return issue

    fetch_started_at = time_monotonic()
    try:
        enriched_issue = await fetch_issue(session, int(issue.comicvine_id))
    except Exception as exc:
        if timing is not None:
            timing.update(
                {
                    "comicvine_issue_fetch_status": "failed",
                    "comicvine_issue_fetch_duration_ms": round(
                        (time_monotonic() - fetch_started_at) * 1000
                    ),
                }
            )
        log_warning(
            "import_comicinfo_issue_enrichment_failed",
            issue_id=issue.id,
            comicvine_issue_id=issue.comicvine_id,
            error=str(exc),
        )
        return issue

    if timing is not None:
        timing.update(
            {
                "comicvine_issue_fetch_status": "fetched",
                "comicvine_issue_fetch_duration_ms": round(
                    (time_monotonic() - fetch_started_at) * 1000
                ),
            }
        )
    return enriched_issue if isinstance(enriched_issue, Issue) else issue
