"""Matching suggestion API routes — list, accept, and dismiss suggestions."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from pullbox.api.deps import AuthenticatedUser, DbSession  # noqa: TC001
from pullbox.core.exceptions import NotFoundError
from pullbox.core.library_policy import load_search_on_add_default
from pullbox.models.library import LibraryFile
from pullbox.models.matching_suggestion import MatchingSuggestion, SuggestionStatus
from pullbox.schemas.suggestion import SuggestionAccept, SuggestionResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["suggestions"])


@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_suggestions(
    user: AuthenticatedUser,
    session: DbSession,
    status: Annotated[SuggestionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SuggestionResponse]:
    """List matching suggestions, optionally filtered by status."""
    query = select(MatchingSuggestion).options(
        joinedload(MatchingSuggestion.library_file),
        joinedload(MatchingSuggestion.parent_series),
    )

    if status:
        query = query.where(MatchingSuggestion.status == status)
    else:
        # Default to pending only
        query = query.where(MatchingSuggestion.status == SuggestionStatus.PENDING)

    query = query.order_by(MatchingSuggestion.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    suggestions = list(result.unique().scalars().all())

    return [_to_response(s) for s in suggestions]


@router.get("/suggestions/count")
async def suggestion_count(
    user: AuthenticatedUser,
    session: DbSession,
) -> dict[str, int]:
    """Get the count of pending suggestions."""
    count: int = (
        await session.execute(
            select(func.count(MatchingSuggestion.id)).where(
                MatchingSuggestion.status == SuggestionStatus.PENDING,
            )
        )
    ).scalar_one()
    return {"pending": count}


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: int,
    body: SuggestionAccept,
    user: AuthenticatedUser,
    session: DbSession,
) -> dict[str, object]:
    """Accept a suggestion: add the series from ComicVine and match the file.

    This creates the suggested series (with parent linkage), creates its
    folder, and triggers matching for the associated file.
    """
    suggestion = await session.get(MatchingSuggestion, suggestion_id)
    if not suggestion:
        raise NotFoundError("MatchingSuggestion", suggestion_id)

    if suggestion.status != SuggestionStatus.PENDING:
        from pullbox.core.exceptions import ValidationError

        raise ValidationError(f"Suggestion is already {suggestion.status}")

    # Build domain services through the shared composition surface.
    from pullbox.composition.services import build_domain_series_service, build_matching_service

    series_svc = await build_domain_series_service(session)
    search_on_add = await load_search_on_add_default(session)

    # Add the series from ComicVine
    new_series = await series_svc.add_from_comicvine(
        session,
        comicvine_id=body.comicvine_id,
        library_root_id=body.library_root_id,
        search_on_add=search_on_add,
    )

    # Mark suggestion as accepted
    suggestion.status = SuggestionStatus.ACCEPTED
    suggestion.suggested_comicvine_id = body.comicvine_id

    # Re-run matching for the file
    library_file = await session.get(LibraryFile, suggestion.library_file_id)
    if library_file:
        matching_svc = build_matching_service()
        await matching_svc.match_file(session, library_file)

    await session.flush()

    logger.info(
        "suggestion_accepted",
        suggestion_id=suggestion_id,
        series_id=new_series.id,
        comicvine_id=body.comicvine_id,
    )

    return {
        "message": f"Added '{new_series.title}' and re-matched file.",
        "series_id": new_series.id,
    }


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> dict[str, str]:
    """Dismiss a suggestion — marks it as not actionable."""
    suggestion = await session.get(MatchingSuggestion, suggestion_id)
    if not suggestion:
        raise NotFoundError("MatchingSuggestion", suggestion_id)

    suggestion.status = SuggestionStatus.DISMISSED
    logger.info("suggestion_dismissed", suggestion_id=suggestion_id)
    return {"message": "Suggestion dismissed."}


def _to_response(s: MatchingSuggestion) -> SuggestionResponse:
    """Convert a MatchingSuggestion ORM object to a response schema."""
    return SuggestionResponse(
        id=s.id,
        library_file_id=s.library_file_id,
        parent_series_id=s.parent_series_id,
        suggested_comicvine_id=s.suggested_comicvine_id,
        suggested_title=s.suggested_title,
        suggested_year=s.suggested_year,
        suggested_publisher=s.suggested_publisher,
        suggested_series_type=s.suggested_series_type,
        detection_source=s.detection_source,
        confidence_score=s.confidence_score,
        reason=s.reason,
        status=s.status,
        file_name=s.library_file.file_name if s.library_file else None,
        parent_series_title=s.parent_series.title if s.parent_series else None,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )
