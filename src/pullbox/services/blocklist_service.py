"""Blocklist service — CRUD and filtering for blocked releases."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import contains_eager, joinedload

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.providers.base import ReleaseResult

logger = structlog.get_logger(__name__)

# Characters treated as equivalent separators in group name matching
_GROUP_SEPARATORS = str.maketrans({"-": "", "_": "", ".": "", " ": ""})


def _normalize_group(name: str) -> str:
    """Normalize a release group name for comparison.

    Strips hyphens, dots, underscores, spaces, and lowercases so that
    'Darkness-Empire', 'Darkness Empire', 'darkness_empire' all match.
    Preserves '*' wildcards for pattern matching.
    """
    return name.translate(_GROUP_SEPARATORS).lower()


class BlocklistService:
    """Manages blocklist entries — add, remove, list, check, and filter."""

    @staticmethod
    async def add_entry(
        session: AsyncSession,
        release_title: str,
        reason: BlocklistReason,
        *,
        download_url: str | None = None,
        series_id: int | None = None,
        issue_id: int | None = None,
        indexer_id: int | None = None,
        error_message: str | None = None,
        release_group: str | None = None,
        download_history_id: int | None = None,
    ) -> BlocklistEntry | None:
        """Add a release to the blocklist. Returns None if duplicate."""
        normalized = normalize_release_title(release_title)

        # Check for duplicate by normalized title
        existing = await session.execute(
            select(BlocklistEntry.id).where(BlocklistEntry.release_title_normalized == normalized)
        )
        if existing.scalar_one_or_none() is not None:
            logger.debug(
                "blocklist_duplicate_skipped",
                title=release_title,
                normalized=normalized,
            )
            return None

        entry = BlocklistEntry(
            release_title=release_title,
            release_title_normalized=normalized,
            reason=reason,
            download_url=download_url,
            series_id=series_id,
            issue_id=issue_id,
            indexer_id=indexer_id,
            error_message=error_message,
            release_group=release_group,
            download_history_id=download_history_id,
        )
        session.add(entry)
        await session.flush()
        # Refresh to load joined relationships (series, issue, indexer)
        # so callers can access them without triggering lazy loads
        await session.refresh(entry, attribute_names=["series", "issue", "indexer"])

        logger.info(
            "blocklist_entry_added",
            entry_id=entry.id,
            reason=reason.value,
            title=release_title,
        )
        return entry

    @staticmethod
    async def remove_entry(session: AsyncSession, entry_id: int) -> bool:
        """Remove a blocklist entry by ID. Returns True if removed."""
        if entry_id <= 0:
            return False

        entry = await session.get(BlocklistEntry, entry_id)
        if entry is None:
            return False

        await session.delete(entry)
        await session.flush()
        logger.info("blocklist_entry_removed", entry_id=entry_id)
        return True

    @staticmethod
    async def remove_entries(session: AsyncSession, entry_ids: list[int]) -> int:
        """Remove multiple entries. Returns count of removed."""
        if not entry_ids:
            return 0

        valid_ids = [eid for eid in entry_ids if eid > 0]
        if not valid_ids:
            return 0

        result = await session.execute(
            delete(BlocklistEntry).where(BlocklistEntry.id.in_(valid_ids))
        )
        count: int = result.rowcount  # type: ignore[attr-defined]
        await session.flush()

        if count > 0:
            logger.info("blocklist_entries_bulk_removed", count=count)
        return count

    @staticmethod
    async def clear_entries(session: AsyncSession) -> int:
        """Remove all blocklist entries and return the count removed."""
        result = await session.execute(delete(BlocklistEntry))
        count: int = result.rowcount  # type: ignore[attr-defined]
        await session.flush()

        if count > 0:
            logger.info("blocklist_entries_cleared", count=count)
        return count

    @staticmethod
    async def get_entry(session: AsyncSession, entry_id: int) -> BlocklistEntry | None:
        """Get a single entry by ID."""
        if entry_id <= 0:
            return None
        result = await session.execute(
            select(BlocklistEntry)
            .options(
                joinedload(BlocklistEntry.series),
                joinedload(BlocklistEntry.issue),
                joinedload(BlocklistEntry.indexer),
            )
            .where(BlocklistEntry.id == entry_id)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def list_entries(
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        reason: BlocklistReason | None = None,
        series_id: int | None = None,
        search: str | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[BlocklistEntry], int]:
        """List entries with filtering, sorting, and pagination.

        Returns (entries, total_count) where total_count reflects all
        matching entries, not just the current page.

        Sort format: field name, prefixed with "-" for descending.
        Valid fields: title, reason, release_group, created_at.
        """
        from pullbox.models.series import Series

        # Build base filter conditions
        conditions = []
        if reason is not None:
            conditions.append(BlocklistEntry.reason == reason)
        if series_id is not None:
            conditions.append(BlocklistEntry.series_id == series_id)
        if search and search.strip():
            conditions.append(
                BlocklistEntry.release_title_normalized.ilike(f"%{search.strip().lower()}%")
            )

        # Count query
        count_query = select(func.count(BlocklistEntry.id))
        for cond in conditions:
            count_query = count_query.where(cond)
        total = (await session.execute(count_query)).scalar_one()

        # Sort mapping
        desc = sort.startswith("-")
        field = sort.lstrip("-")
        sort_columns = {
            "title": BlocklistEntry.release_title,
            "reason": BlocklistEntry.reason,
            "release_group": BlocklistEntry.release_group,
            "created_at": BlocklistEntry.created_at,
            "series": Series.title,
        }
        col = sort_columns.get(field, BlocklistEntry.created_at)
        order = col.desc() if desc else col.asc()

        # Data query
        data_query = select(BlocklistEntry).options(
            joinedload(BlocklistEntry.issue),
            joinedload(BlocklistEntry.indexer),
        )
        if field == "series":
            data_query = data_query.outerjoin(
                Series, BlocklistEntry.series_id == Series.id
            ).options(contains_eager(BlocklistEntry.series))
        else:
            data_query = data_query.options(joinedload(BlocklistEntry.series))
        for cond in conditions:
            data_query = data_query.where(cond)
        data_query = data_query.order_by(order).limit(limit).offset(offset)

        result = await session.execute(data_query)
        entries = list(result.scalars().all())

        return entries, total

    @staticmethod
    async def count_entries(session: AsyncSession) -> int:
        """Count total blocklist entries."""
        result = await session.execute(select(func.count(BlocklistEntry.id)))
        return result.scalar_one()

    @staticmethod
    async def count_entries_by_reason(
        session: AsyncSession,
        *,
        reason: BlocklistReason | None = None,
        series_id: int | None = None,
        search: str | None = None,
    ) -> dict[BlocklistReason, int]:
        """Return grouped counts for the current filtered blocklist scope."""
        conditions = []
        if reason is not None:
            conditions.append(BlocklistEntry.reason == reason)
        if series_id is not None:
            conditions.append(BlocklistEntry.series_id == series_id)
        if search and search.strip():
            conditions.append(
                BlocklistEntry.release_title_normalized.ilike(f"%{search.strip().lower()}%")
            )

        query = select(BlocklistEntry.reason, func.count(BlocklistEntry.id)).group_by(
            BlocklistEntry.reason
        )
        for cond in conditions:
            query = query.where(cond)

        result = await session.execute(query)
        grouped = {key: 0 for key in BlocklistReason}
        for reason_value, count in result.all():
            grouped[BlocklistReason(reason_value)] = int(count)
        return grouped

    # ── Check / Filter methods ────────────────────────────────────────

    @staticmethod
    async def is_release_blocked(session: AsyncSession, title: str) -> bool:
        """Check if a release title is in the blocklist (case/whitespace insensitive)."""
        if not title or not title.strip():
            return False
        normalized = normalize_release_title(title)
        result = await session.execute(
            select(BlocklistEntry.id).where(BlocklistEntry.release_title_normalized == normalized)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_blocked_groups(session: AsyncSession) -> set[str]:
        """Get the set of blocked release groups from SystemConfig."""
        from pullbox.models.config import SystemConfig

        result = await session.execute(
            select(SystemConfig.value).where(SystemConfig.key == "blocklist.release_groups")
        )
        raw = result.scalar_one_or_none() or ""
        return {_normalize_group(g) for g in raw.split(",") if g.strip()}

    @staticmethod
    def is_group_blocked(release_group: str | None, blocked_groups: set[str]) -> bool:
        """Check if a release group matches any blocked pattern.

        Normalizes separators (hyphens, dots, underscores, spaces) so that
        'Darkness-Empire' matches 'Darkness Empire', 'darkness_empire', etc.

        Supports wildcards:
        - '*Empire'  → blocks any group ending with 'empire'
        - 'Green*'   → blocks any group starting with 'green'
        - '*Green*'  → blocks any group containing 'green'
        - 'Empire'   → exact match only
        """
        if not release_group or not blocked_groups:
            return False
        normalized = _normalize_group(release_group)
        for pattern in blocked_groups:
            if pattern.startswith("*") and pattern.endswith("*") and len(pattern) > 2:
                if pattern[1:-1] in normalized:
                    return True
            elif pattern.startswith("*"):
                if normalized.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("*"):
                if normalized.startswith(pattern[:-1]):
                    return True
            elif normalized == pattern:
                return True
        return False

    @staticmethod
    async def filter_results(
        session: AsyncSession,
        results: list[ReleaseResult],
    ) -> list[ReleaseResult]:
        """Filter out results whose titles are blocklisted or whose groups are blocked.

        Returns a new list — does not modify the original.
        """
        if not results:
            return []

        from pullbox.core.release_parser import parse_release_title

        # Load all blocked normalized titles in one query
        bl_result = await session.execute(select(BlocklistEntry.release_title_normalized))
        blocked_titles = {row[0] for row in bl_result.all()}

        # Load blocked groups from config
        blocked_groups = await BlocklistService.get_blocked_groups(session)

        kept: list[ReleaseResult] = []
        removed = 0

        for release in results:
            normalized = normalize_release_title(release.title)

            # Check title blocklist
            if normalized in blocked_titles:
                removed += 1
                continue

            # Check group blocklist
            if blocked_groups:
                parsed = parse_release_title(release.title)
                if parsed and BlocklistService.is_group_blocked(parsed.scan_group, blocked_groups):
                    removed += 1
                    continue

            kept.append(release)

        if removed > 0:
            logger.info(
                "blocklist_filter_applied",
                total=len(results),
                removed=removed,
                remaining=len(kept),
            )

        return kept
