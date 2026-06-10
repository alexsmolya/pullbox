"""Blocklist API endpoints — CRUD for blocked releases."""

import structlog
from fastapi import APIRouter, Query

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.exceptions import NotFoundError
from pullbox.models.blocklist import BlocklistReason
from pullbox.schemas.blocklist import (
    BlocklistAddRequest,
    BlocklistBulkDeleteRequest,
    BlocklistBulkDeleteResponse,
    BlocklistCountResponse,
    BlocklistEntryResponse,
    BlocklistListResponse,
    ReleaseGroupListRequest,
    ReleaseGroupListResponse,
)
from pullbox.services.blocklist_service import BlocklistService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/blocklist", tags=["blocklist"])


def _entry_to_response(entry: object) -> BlocklistEntryResponse:
    """Convert a BlocklistEntry ORM model to a response schema."""
    from pullbox.models.blocklist import BlocklistEntry

    assert isinstance(entry, BlocklistEntry)
    series_title = entry.series.title if entry.series else None
    return BlocklistEntryResponse(
        id=entry.id,
        release_title=entry.release_title,
        release_title_normalized=entry.release_title_normalized,
        download_url=entry.download_url,
        series_id=entry.series_id,
        issue_id=entry.issue_id,
        indexer_id=entry.indexer_id,
        reason=entry.reason,
        error_message=entry.error_message,
        release_group=entry.release_group,
        download_history_id=entry.download_history_id,
        series_title=series_title,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/count", response_model=BlocklistCountResponse)
async def get_count(
    _user: AuthenticatedUser,
    session: DbSession,
) -> BlocklistCountResponse:
    """Return total blocklist entry count."""
    count = await BlocklistService.count_entries(session)
    return BlocklistCountResponse(count=count)


# ── Release Group Config Endpoints ────────────────────────────────────
# These must be declared BEFORE /{entry_id} to avoid route conflict.


@router.get("/groups")
async def get_release_groups(
    _user: AuthenticatedUser,
    session: DbSession,
) -> ReleaseGroupListResponse:
    """Get the current release group blocklist."""
    from pullbox.models.config import SystemConfig

    row = await session.get(SystemConfig, "blocklist.release_groups")
    raw = row.value if row else ""
    groups = [g.strip() for g in raw.split(",") if g.strip()]
    return ReleaseGroupListResponse(groups=groups)


@router.put("/groups")
async def update_release_groups(
    body: ReleaseGroupListRequest,
    _user: AuthenticatedUser,
    session: DbSession,
) -> ReleaseGroupListResponse:
    """Update the release group blocklist."""
    from pullbox.models.config import SystemConfig

    # Deduplicate (case-insensitive), trim whitespace, filter empty
    seen: set[str] = set()
    clean: list[str] = []
    for g in body.groups:
        trimmed = g.strip()
        if not trimmed:
            continue
        key = trimmed.lower()
        if key not in seen:
            seen.add(key)
            clean.append(trimmed)

    value = ",".join(clean)

    row = await session.get(SystemConfig, "blocklist.release_groups")
    if row:
        row.value = value
    else:
        session.add(
            SystemConfig(
                key="blocklist.release_groups",
                value=value,
                value_type="string",
            )
        )
    await session.flush()

    logger.info("blocklist_release_groups_updated", groups=clean, count=len(clean))
    return ReleaseGroupListResponse(groups=clean)


# ── Single Entry Endpoints ────────────────────────────────────────────


@router.get("/{entry_id}", response_model=BlocklistEntryResponse)
async def get_entry(
    entry_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> BlocklistEntryResponse:
    """Get a single blocklist entry."""
    entry = await BlocklistService.get_entry(session, entry_id)
    if entry is None:
        raise NotFoundError("BlocklistEntry", entry_id)
    return _entry_to_response(entry)


@router.get("", response_model=BlocklistListResponse)
async def list_entries(
    _user: AuthenticatedUser,
    session: DbSession,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=0, le=100, description="Items per page"),
    reason: BlocklistReason | None = None,
    series_id: int | None = None,
    search: str | None = None,
) -> BlocklistListResponse:
    """List blocklist entries with pagination and filtering."""
    offset = (page - 1) * page_size
    entries, total = await BlocklistService.list_entries(
        session,
        limit=page_size,
        offset=offset,
        reason=reason,
        series_id=series_id,
        search=search,
    )
    return BlocklistListResponse(
        entries=[_entry_to_response(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=BlocklistEntryResponse, status_code=201)
async def add_entry(
    body: BlocklistAddRequest,
    _user: AuthenticatedUser,
    session: DbSession,
) -> BlocklistEntryResponse:
    """Manually add a release to the blocklist."""
    entry = await BlocklistService.add_entry(
        session,
        body.release_title,
        body.reason,
        download_url=body.download_url,
        series_id=body.series_id,
        issue_id=body.issue_id,
    )
    if entry is None:
        # Duplicate — return 409
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail={"error": {"message": "Release already in blocklist"}},
        )
    return _entry_to_response(entry)


@router.delete("/bulk", response_model=BlocklistBulkDeleteResponse)
async def bulk_delete(
    body: BlocklistBulkDeleteRequest,
    _user: AuthenticatedUser,
    session: DbSession,
) -> BlocklistBulkDeleteResponse:
    """Remove multiple blocklist entries."""
    count = await BlocklistService.remove_entries(session, body.ids)
    return BlocklistBulkDeleteResponse(removed=count)


@router.delete("/clear", response_model=BlocklistBulkDeleteResponse)
async def clear_entries(
    _user: AuthenticatedUser,
    session: DbSession,
) -> BlocklistBulkDeleteResponse:
    """Remove all blocklist entries."""
    count = await BlocklistService.clear_entries(session)
    return BlocklistBulkDeleteResponse(removed=count)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> None:
    """Remove a single blocklist entry."""
    removed = await BlocklistService.remove_entry(session, entry_id)
    if not removed:
        raise NotFoundError("BlocklistEntry", entry_id)
