"""Search API routes — ComicVine series search, indexer release search, library search."""

import structlog
from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, func, select

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.exceptions import NotFoundError
from pullbox.models.library import LibraryFile, MatchConfidence
from pullbox.models.search_log import SearchLog
from pullbox.models.series import Series
from pullbox.schemas.search import (
    LibrarySearchResult,
    ReleaseSearchResult,
    SearchHistoryBulkDeleteResponse,
    SeriesSearchResult,
)
from pullbox.services.direct_discovery_retention import prune_unstarted_direct_discoveries

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# ── ComicVine Series Search ──────────────────────────────────────────


@router.get("/series", response_model=list[SeriesSearchResult])
async def search_series(
    _user: AuthenticatedUser,
    session: DbSession,
    q: str = Query(..., min_length=1, description="Search query"),
    year: int | None = Query(None, description="Filter by start year"),
) -> list[SeriesSearchResult]:
    """Search ComicVine for series by title."""
    from pullbox.core.comicvine_key import get_comicvine_api_key
    from pullbox.providers.metadata.comicvine import ComicVineProvider

    api_key = await get_comicvine_api_key(session)
    provider = ComicVineProvider(api_key=api_key)
    results = await provider.search_series(q, year=year)

    # Check which series are already in the library
    comicvine_ids = [int(r.provider_id) for r in results]
    existing_result = await session.execute(
        select(Series.comicvine_id).where(Series.comicvine_id.in_(comicvine_ids))
    )
    existing_ids = {row[0] for row in existing_result.all()}

    return [
        SeriesSearchResult(
            comicvine_id=int(r.provider_id),
            title=r.title,
            year_start=r.year_start,
            publisher_name=r.publisher,
            issue_count=r.issue_count,
            description=r.description,
            cover_url=r.cover_url,
            comicvine_url=None,
            already_added=int(r.provider_id) in existing_ids,
        )
        for r in results
    ]


# ── Release Search ───────────────────────────────────────────────────


@router.get("/releases", response_model=list[ReleaseSearchResult])
async def search_releases(
    _user: AuthenticatedUser,
    session: DbSession,
    series: str = Query(..., min_length=1, description="Series title"),
    issue: float | None = Query(None, description="Issue number"),
    year: int | None = Query(None, description="Year filter"),
) -> list[ReleaseSearchResult]:
    """Search all enabled indexers for releases."""
    from pullbox.providers.base import SearchQuery
    from pullbox.services.search_service import SearchService, build_search_runtime

    runtime = await build_search_runtime(session, include_download_clients=False)
    if runtime is None:
        return []

    search_svc = SearchService(
        registry=runtime.registry,
        failure_threshold=runtime.failure_threshold,
        ignore_indexer_backoff=True,
    )
    query = SearchQuery(series_title=series, issue_number=issue, year=year)
    all_results = await search_svc.search(query, indexer_configs=runtime.indexer_configs)

    return [
        ReleaseSearchResult(
            title=r.title,
            download_url=r.download_url,
            indexer_id=0,
            indexer_name=r.indexer_name,
            size_bytes=r.size_bytes,
            publish_date=r.published_at.date() if r.published_at else None,
            seeders=r.seeders,
            leechers=r.leechers,
        )
        for r in all_results
    ]


# ── Library Search ───────────────────────────────────────────────────


@router.get("/library", response_model=list[LibrarySearchResult])
async def search_library(
    _user: AuthenticatedUser,
    session: DbSession,
    q: str = Query(..., min_length=1, description="Search filename or parsed series"),
    limit: int = Query(50, ge=1, le=200),
) -> list[LibrarySearchResult]:
    """Search local library files by filename or parsed series name."""
    from pullbox.core.db_utils import escape_like

    pattern = f"%{escape_like(q)}%"
    result = await session.execute(
        select(LibraryFile)
        .where(LibraryFile.file_name.ilike(pattern) | LibraryFile.parsed_series.ilike(pattern))
        .order_by(LibraryFile.file_name)
        .limit(limit)
    )
    files = result.scalars().all()

    return [
        LibrarySearchResult(
            file_id=f.id,
            file_name=f.file_name,
            file_path=f.file_path,
            series_title=f.parsed_series,
            issue_number=f.parsed_issue_number,
            matched=f.match_confidence != MatchConfidence.UNMATCHED,
        )
        for f in files
    ]


@router.delete("/history/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_history_entry(
    log_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Delete a single search history record."""
    log = await session.get(SearchLog, log_id)
    if log is None:
        raise NotFoundError("SearchLog", log_id)

    await prune_unstarted_direct_discoveries(session, [log_id])
    await session.delete(log)
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/history", response_model=SearchHistoryBulkDeleteResponse)
async def clear_search_history(
    _user: AuthenticatedUser,
    session: DbSession,
) -> SearchHistoryBulkDeleteResponse:
    """Delete all search history records."""
    result = await session.execute(select(func.count(SearchLog.id)))
    deleted = result.scalar_one()

    if deleted:
        await prune_unstarted_direct_discoveries(session, select(SearchLog.id))
        await session.execute(delete(SearchLog))
        await session.flush()

    return SearchHistoryBulkDeleteResponse(deleted=deleted)
