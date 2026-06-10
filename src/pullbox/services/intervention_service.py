"""Intervention queue service — manages pending matches for user review.

When a search finds a release with medium or low confidence, it is
stored as a PendingMatch for the user to approve or reject via the
intervention queue UI. This service handles all CRUD and lifecycle
operations for pending matches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select, update

from pullbox.models.pending_match import PendingMatch, PendingMatchStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.download import DownloadHistory
    from pullbox.providers.base import ReleaseResult
    from pullbox.services.download_service import DownloadService
    from pullbox.services.release_validator import ValidationResult

logger = structlog.get_logger(__name__)


class InterventionService:
    """Manages the intervention queue for ambiguous search matches."""

    def __init__(
        self,
        download_service: DownloadService | None = None,
    ) -> None:
        self._download_service = download_service

    async def create_pending_match(
        self,
        session: AsyncSession,
        issue_id: int,
        release: ReleaseResult,
        validation: ValidationResult,
        indexer_id: int | None = None,
    ) -> PendingMatch | None:
        """Create a pending match if one doesn't already exist for this issue+URL.

        Returns None if a duplicate already exists.
        """
        # Check for existing pending match with same issue+URL
        existing = await session.execute(
            select(PendingMatch).where(
                PendingMatch.issue_id == issue_id,
                PendingMatch.download_url == release.download_url,
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.debug(
                "pending_match_duplicate_skipped",
                issue_id=issue_id,
                url=release.download_url,
            )
            return None

        match_details: dict[str, object] = {
            "parsed_series": getattr(validation.parsed, "series_name", None),
            "parsed_issue": getattr(validation.parsed, "issue_number", None),
            "parsed_year": getattr(validation.parsed, "year", None),
            "parsed_type": getattr(getattr(validation.parsed, "issue_type", None), "value", None),
            "series_similarity": validation.series_similarity,
            "series_match_type": ("exact" if validation.series_similarity >= 0.95 else "fuzzy"),
            "issue_match": validation.issue_match,
            "year_match": validation.year_match,
            "type_match": validation.issue_type_match,
            "rejection_flags": [],
            "size_warning": None,
            "indexer_name": release.indexer_name,
            "age_days": release.age_days,
            "seeders": release.seeders,
            "leechers": release.leechers,
            "info_url": release.info_url,
        }

        pm = PendingMatch(
            issue_id=issue_id,
            release_title=release.title,
            download_url=release.download_url,
            indexer_id=indexer_id,
            is_torrent=release.is_torrent,
            file_size=release.size_bytes,
            confidence=validation.confidence.value,
            match_details=match_details,
        )
        session.add(pm)
        await session.flush()

        logger.info(
            "pending_match_created",
            pending_id=pm.id,
            issue_id=issue_id,
            confidence=validation.confidence.value,
            release_title=release.title,
        )
        return pm

    async def approve_match(
        self,
        session: AsyncSession,
        pending_id: int,
    ) -> DownloadHistory:
        """Approve a pending match and send it to the download client.

        Raises:
            ValueError: If pending match not found or not in PENDING status.
        """
        pm = await session.get(PendingMatch, pending_id)
        if pm is None:
            raise ValueError(f"Pending match {pending_id} not found")
        if pm.status != PendingMatchStatus.PENDING:
            raise ValueError(f"Pending match {pending_id} is not pending (status={pm.status})")

        if self._download_service is None:
            raise RuntimeError("No download service configured")

        # Reconstruct ReleaseResult from stored data
        from pullbox.providers.base import ReleaseResult

        release = ReleaseResult(
            title=pm.release_title,
            indexer_name=pm.match_details.get("indexer_name", "unknown"),
            download_url=pm.download_url,
            size_bytes=pm.file_size,
            age_days=pm.match_details.get("age_days"),
            seeders=pm.match_details.get("seeders"),
            leechers=pm.match_details.get("leechers"),
            grabs=None,
            is_torrent=pm.is_torrent,
            category=None,
            published_at=None,
        )

        download = await self._download_service.send_to_client(
            session, release, pm.issue_id, pm.indexer_id
        )

        pm.status = PendingMatchStatus.APPROVED
        pm.resolved_at = datetime.now(UTC)
        pm.resolved_by = "user"

        logger.info(
            "pending_match_approved",
            pending_id=pending_id,
            issue_id=pm.issue_id,
            release_title=pm.release_title,
        )
        return download

    async def reject_match(
        self,
        session: AsyncSession,
        pending_id: int,
        reason: str | None = None,
    ) -> None:
        """Reject a pending match.

        Raises:
            ValueError: If pending match not found or not in PENDING status.
        """
        pm = await session.get(PendingMatch, pending_id)
        if pm is None:
            raise ValueError(f"Pending match {pending_id} not found")
        if pm.status != PendingMatchStatus.PENDING:
            raise ValueError(f"Pending match {pending_id} is not pending (status={pm.status})")

        pm.status = PendingMatchStatus.REJECTED
        pm.resolved_at = datetime.now(UTC)
        pm.resolved_by = "user"

        if reason:
            details = dict(pm.match_details) if pm.match_details else {}
            details["rejection_reason"] = reason
            pm.match_details = details

        logger.info(
            "pending_match_rejected",
            pending_id=pending_id,
            issue_id=pm.issue_id,
            reason=reason,
        )

        # Add to blocklist so this release is not grabbed again
        try:
            from pullbox.core.release_parser import parse_release_title
            from pullbox.models.blocklist import BlocklistReason
            from pullbox.services.blocklist_service import BlocklistService

            parsed = parse_release_title(pm.release_title)
            release_group = parsed.scan_group if parsed else None

            await BlocklistService.add_entry(
                session,
                pm.release_title,
                BlocklistReason.REJECTED,
                download_url=pm.download_url,
                issue_id=pm.issue_id,
                indexer_id=pm.indexer_id,
                release_group=release_group,
            )
        except Exception:
            logger.debug(
                "blocklist_reject_add_failed",
                pending_id=pending_id,
            )

    async def get_pending(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        status: PendingMatchStatus | None = PendingMatchStatus.PENDING,
        series_id: int | None = None,
        confidence: str | None = None,
    ) -> tuple[list[PendingMatch], int]:
        """Get paginated pending matches with optional filters.

        Returns (items, total_count).
        """
        from pullbox.models.issue import Issue

        query = select(PendingMatch)
        count_query = select(func.count(PendingMatch.id))

        if status is not None:
            query = query.where(PendingMatch.status == status)
            count_query = count_query.where(PendingMatch.status == status)

        if series_id is not None:
            query = query.join(Issue, PendingMatch.issue_id == Issue.id).where(
                Issue.series_id == series_id
            )
            count_query = count_query.join(Issue, PendingMatch.issue_id == Issue.id).where(
                Issue.series_id == series_id
            )

        if confidence is not None:
            query = query.where(PendingMatch.confidence == confidence)
            count_query = count_query.where(PendingMatch.confidence == confidence)

        total = (await session.execute(count_query)).scalar_one()

        query = query.order_by(PendingMatch.created_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)

        result = await session.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def get_pending_count(self, session: AsyncSession) -> int:
        """Count pending matches (PENDING status only)."""
        result = await session.execute(
            select(func.count(PendingMatch.id)).where(
                PendingMatch.status == PendingMatchStatus.PENDING
            )
        )
        return result.scalar_one()

    async def expire_stale(
        self,
        session: AsyncSession,
        max_age_days: int = 30,
    ) -> int:
        """Expire PENDING matches older than max_age_days. Returns count expired."""
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

        # Count first, then update — avoids mypy issues with CursorResult.rowcount
        stale = await session.execute(
            select(PendingMatch.id).where(
                PendingMatch.status == PendingMatchStatus.PENDING,
                PendingMatch.created_at < cutoff,
            )
        )
        stale_ids = [row[0] for row in stale.all()]

        if stale_ids:
            await session.execute(
                update(PendingMatch)
                .where(PendingMatch.id.in_(stale_ids))
                .values(
                    status=PendingMatchStatus.EXPIRED,
                    resolved_at=datetime.now(UTC),
                    resolved_by="expiry",
                )
            )
        count = len(stale_ids)

        if count:
            logger.info("pending_matches_expired", count=count, max_age_days=max_age_days)

        return count

    async def has_pending_for_issue(
        self,
        session: AsyncSession,
        issue_id: int,
    ) -> bool:
        """Check if issue already has a PENDING match."""
        result = await session.execute(
            select(func.count(PendingMatch.id)).where(
                PendingMatch.issue_id == issue_id,
                PendingMatch.status == PendingMatchStatus.PENDING,
            )
        )
        return result.scalar_one() > 0
