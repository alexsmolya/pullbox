"""Seed enough dev rows to visually test footer clearance on history pages.

This script is intended for local development only. It is idempotent by page
bucket: each bucket is filled only until it reaches the target count used by the
UI pagination controls.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_footer_gap_data.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus
from pullbox.services.download_history_classification import (
    download_history_clause,
    post_processing_history_clause,
)

TARGET_ROWS = 60
DOWNLOAD_ACTIVE_TARGET_ROWS = 24
DOWNLOAD_WAITING_TARGET_ROWS = 36
SEED_PREFIX = "PB Footer Gap Seed"


def _ago(*, days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days, hours=hours, minutes=minutes)


async def _scalar_count(session: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _count_download_queue(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(
            DownloadHistory.state.in_(
                [
                    DownloadState.QUEUED,
                    DownloadState.SENT,
                    DownloadState.DOWNLOADING,
                    DownloadState.PAUSED,
                    DownloadState.RETRY_PENDING,
                ]
            )
        ),
    )


async def _count_download_active(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(
            DownloadHistory.state.in_([DownloadState.SENT, DownloadState.DOWNLOADING])
        ),
    )


async def _count_download_waiting(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(
            DownloadHistory.state.in_([DownloadState.QUEUED, DownloadState.RETRY_PENDING])
        ),
    )


async def _count_download_history(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(download_history_clause()),
    )


async def _count_post_processing_queue(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(
            DownloadHistory.state == DownloadState.POST_PROCESSING
        ),
    )


async def _count_post_processing_history(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(DownloadHistory.id)).where(post_processing_history_clause()),
    )


async def _count_blocklist(session: AsyncSession) -> int:
    return await _scalar_count(session, select(func.count(BlocklistEntry.id)))


async def _count_intervention_queue(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(PendingMatch.id)).where(
            PendingMatch.status == PendingMatchStatus.PENDING
        ),
    )


async def _count_intervention_history(session: AsyncSession) -> int:
    return await _scalar_count(
        session,
        select(func.count(PendingMatch.id)).where(
            PendingMatch.status != PendingMatchStatus.PENDING
        ),
    )


async def _count_search_history(session: AsyncSession) -> int:
    return await _scalar_count(session, select(func.count(SearchLog.id)))


async def _get_or_create_seed_issues(session: AsyncSession, *, minimum: int = 120) -> list[Issue]:
    series = (
        await session.execute(
            select(Series).where(Series.title == f"{SEED_PREFIX} Series").limit(1)
        )
    ).scalar_one_or_none()
    if series is None:
        series = Series(
            comicvine_id=None,
            title=f"{SEED_PREFIX} Series",
            sort_title=f"{SEED_PREFIX} Series",
            year_start=2026,
            year_end=None,
            status=SeriesStatus.CONTINUING,
            description="Synthetic dev series used to test dense table footer clearance.",
            issue_count=minimum,
            monitored=False,
            metadata_source="seed",
        )
        session.add(series)
        await session.flush()

    existing = list(
        (
            await session.execute(
                select(Issue).where(Issue.series_id == series.id).order_by(Issue.issue_number.asc())
            )
        )
        .scalars()
        .all()
    )
    existing_numbers = {int(issue.issue_number) for issue in existing}
    for issue_number in range(1, minimum + 1):
        if issue_number in existing_numbers:
            continue
        session.add(
            Issue(
                comicvine_id=None,
                series_id=series.id,
                issue_number=float(issue_number),
                title=f"Footer Contract Test {issue_number:03d}",
                status=IssueStatus.WANTED,
                metadata_source="seed",
            )
        )

    series.issue_count = max(series.issue_count or 0, minimum)
    await session.flush()
    return list(
        (
            await session.execute(
                select(Issue).where(Issue.series_id == series.id).order_by(Issue.issue_number.asc())
            )
        )
        .scalars()
        .all()
    )


def _issue_at(issues: list[Issue], index: int) -> Issue:
    return issues[index % len(issues)]


def _touch_timestamps(row: object, index: int) -> None:
    timestamp = _ago(days=index // 8, minutes=index * 9)
    row.created_at = timestamp  # type: ignore[attr-defined]
    row.updated_at = timestamp  # type: ignore[attr-defined]


async def _seed_download_queue(session: AsyncSession, issues: list[Issue], run_id: str) -> int:
    seed_queue_clause = (
        DownloadHistory.title.like(f"{SEED_PREFIX} Active Download%")
        | DownloadHistory.title.like(f"{SEED_PREFIX} Queued Download%")
        | DownloadHistory.title.like(f"{SEED_PREFIX} Download Queue%")
    )
    existing_seed_rows = list(
        (
            await session.execute(
                select(DownloadHistory).where(seed_queue_clause).order_by(DownloadHistory.id.asc())
            )
        )
        .scalars()
        .all()
    )
    required_seed_rows = DOWNLOAD_ACTIVE_TARGET_ROWS + DOWNLOAD_WAITING_TARGET_ROWS
    missing_seed_rows = max(0, required_seed_rows - len(existing_seed_rows))
    for index in range(missing_seed_rows):
        issue = _issue_at(issues, index)
        row = DownloadHistory(
            issue_id=issue.id,
            title=f"{SEED_PREFIX} Download Queue {run_id}-{index + 1:03d}",
            download_url=f"https://seed.pullbox.local/download-queue/{run_id}/{index}",
            download_client=DownloadClientType.SABNZBD,
            external_id=None,
            state=DownloadState.PAUSED,
            file_size=80_000_000 + index * 1_250_000,
            retry_count=0,
            max_retries=3,
            sent_at=None,
            completed_at=None,
            imported_at=None,
            error_message="Synthetic row for footer clearance testing",
        )
        _touch_timestamps(row, index)
        session.add(row)
        existing_seed_rows.append(row)

    await session.flush()

    fresh_now = datetime.now(UTC)
    for index, row in enumerate(existing_seed_rows):
        row.downloaded_path = None
        row.final_path = None
        row.completed_at = None
        row.imported_at = None
        row.next_retry_at = None
        row.updated_at = fresh_now
        if index < DOWNLOAD_ACTIVE_TARGET_ROWS:
            row.state = DownloadState.DOWNLOADING if index % 2 else DownloadState.SENT
            row.external_id = None
            row.sent_at = fresh_now - timedelta(minutes=index)
            row.error_message = None
            row.title = f"{SEED_PREFIX} Active Download {index + 1:03d}"
        elif index < required_seed_rows:
            row.state = DownloadState.QUEUED if index % 2 else DownloadState.RETRY_PENDING
            row.external_id = None
            row.sent_at = None
            row.next_retry_at = (
                fresh_now + timedelta(hours=2) if row.state == DownloadState.RETRY_PENDING else None
            )
            row.error_message = (
                "Synthetic retry-pending row for footer clearance testing"
                if row.state == DownloadState.RETRY_PENDING
                else None
            )
            row.title = (
                f"{SEED_PREFIX} Queued Download {index - DOWNLOAD_ACTIVE_TARGET_ROWS + 1:03d}"
            )
        else:
            row.state = DownloadState.PAUSED
            row.external_id = None
            row.sent_at = fresh_now - timedelta(hours=1, minutes=index)
            row.error_message = "Synthetic paused row for footer clearance testing"

    existing_seed_rows = list(
        (
            await session.execute(
                select(DownloadHistory).where(seed_queue_clause).order_by(DownloadHistory.id.asc())
            )
        )
        .scalars()
        .all()
    )

    current = await _count_download_queue(session)
    needed = max(0, TARGET_ROWS - current)
    for index in range(needed):
        issue = _issue_at(issues, index)
        row = DownloadHistory(
            issue_id=issue.id,
            title=f"{SEED_PREFIX} Download Queue {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/download-queue/{run_id}/{index}",
            download_client=DownloadClientType.SABNZBD,
            external_id=None,
            state=DownloadState.PAUSED,
            file_size=80_000_000 + index * 1_250_000,
            retry_count=index % 3,
            max_retries=3,
            sent_at=_ago(minutes=index * 7),
            completed_at=None,
            imported_at=None,
            error_message="Synthetic paused row for footer clearance testing",
        )
        _touch_timestamps(row, index)
        session.add(row)
    return needed + missing_seed_rows


async def _seed_download_history(session: AsyncSession, issues: list[Issue], run_id: str) -> int:
    current = await _count_download_history(session)
    needed = max(0, TARGET_ROWS - current)
    for index in range(needed):
        issue = _issue_at(issues, index + 20)
        completed = index % 3 != 0
        row = DownloadHistory(
            issue_id=issue.id,
            title=f"{SEED_PREFIX} Download History {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/download-history/{run_id}/{index}",
            download_client=DownloadClientType.NZBGET if index % 2 else DownloadClientType.SABNZBD,
            external_id=f"footer-gap-dh-{run_id}-{index}",
            state=DownloadState.COMPLETED if completed else DownloadState.FAILED,
            file_size=48_000_000 + index * 850_000,
            downloaded_path=None,
            completed_at=_ago(hours=1, minutes=index * 11),
            imported_at=None,
            error_message=None if completed else "Cancelled by user",
        )
        _touch_timestamps(row, index + 40)
        session.add(row)
    return needed


async def _seed_post_processing_queue(
    session: AsyncSession,
    issues: list[Issue],
    run_id: str,
) -> int:
    current = await _count_post_processing_queue(session)
    needed = max(0, TARGET_ROWS - current)
    for index in range(needed):
        issue = _issue_at(issues, index + 40)
        row = DownloadHistory(
            issue_id=issue.id,
            title=f"{SEED_PREFIX} Post-Processing Queue {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/post-processing-queue/{run_id}/{index}",
            download_client=DownloadClientType.SABNZBD,
            external_id=f"footer-gap-ppq-{run_id}-{index}",
            state=DownloadState.POST_PROCESSING,
            file_size=105_000_000 + index * 1_500_000,
            downloaded_path=f"/downloads/footer-gap/queue-{index + 1:03d}.cbr",
            final_path=None,
            completed_at=_ago(minutes=index * 5),
            imported_at=None,
            error_message=None,
        )
        _touch_timestamps(row, index + 80)
        session.add(row)
    return needed


async def _seed_post_processing_history(
    session: AsyncSession,
    issues: list[Issue],
    run_id: str,
) -> int:
    current = await _count_post_processing_history(session)
    needed = max(0, TARGET_ROWS - current)
    for index in range(needed):
        issue = _issue_at(issues, index + 60)
        failed = index % 4 == 0
        row = DownloadHistory(
            issue_id=issue.id,
            title=f"{SEED_PREFIX} Post-Processing History {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/post-processing-history/{run_id}/{index}",
            download_client=DownloadClientType.QBITTORRENT
            if index % 2
            else DownloadClientType.SABNZBD,
            external_id=f"footer-gap-pph-{run_id}-{index}",
            state=DownloadState.FAILED if failed else DownloadState.COMPLETED,
            file_size=92_000_000 + index * 950_000,
            downloaded_path=f"/downloads/footer-gap/history-{index + 1:03d}.cbz",
            final_path=None
            if failed
            else f"/comics/Footer Gap Seed/Footer Gap Seed {index + 1:03d}.cbz",
            completed_at=_ago(hours=2, minutes=index * 6),
            imported_at=None if failed else _ago(hours=1, minutes=index * 4),
            error_message="Synthetic post-processing failure for footer testing"
            if failed
            else None,
        )
        _touch_timestamps(row, index + 120)
        session.add(row)
    return needed


async def _seed_blocklist(session: AsyncSession, issues: list[Issue], run_id: str) -> int:
    current = await _count_blocklist(session)
    needed = max(0, TARGET_ROWS - current)
    reasons = [BlocklistReason.FAILED, BlocklistReason.REJECTED, BlocklistReason.MANUAL]
    for index in range(needed):
        issue = _issue_at(issues, index + 80)
        title = f"{SEED_PREFIX} Blocklist Release {run_id}-{index + 1:03d}"
        row = BlocklistEntry(
            release_title=title,
            release_title_normalized=normalize_release_title(title),
            download_url=f"https://seed.pullbox.local/blocklist/{run_id}/{index}",
            series_id=issue.series_id,
            issue_id=issue.id,
            reason=reasons[index % len(reasons)],
            error_message="Synthetic blocklist entry for footer clearance testing.",
            release_group=f"FooterSeed{index % 7}",
        )
        _touch_timestamps(row, index + 160)
        session.add(row)
    return needed


async def _seed_intervention_queue(
    session: AsyncSession,
    issues: list[Issue],
    run_id: str,
) -> int:
    current = await _count_intervention_queue(session)
    needed = max(0, TARGET_ROWS - current)
    confidences = ["high", "medium", "low"]
    for index in range(needed):
        issue = _issue_at(issues, index + 100)
        row = PendingMatch(
            issue_id=issue.id,
            release_title=f"{SEED_PREFIX} Intervention Queue {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/intervention-queue/{run_id}/{index}",
            is_torrent=bool(index % 2),
            file_size=70_000_000 + index * 1_100_000,
            confidence=confidences[index % len(confidences)],
            match_details={
                "series_match_type": "fuzzy" if index % 2 else "exact",
                "issue_match": index % 3 != 0,
                "year_match": index % 4 != 0,
                "type_match": index % 5 != 0,
                "indexer_name": "Footer Gap Seed Indexer",
            },
            status=PendingMatchStatus.PENDING,
        )
        _touch_timestamps(row, index + 200)
        session.add(row)
    return needed


async def _seed_intervention_history(
    session: AsyncSession,
    issues: list[Issue],
    run_id: str,
) -> int:
    current = await _count_intervention_history(session)
    needed = max(0, TARGET_ROWS - current)
    statuses = [
        PendingMatchStatus.APPROVED,
        PendingMatchStatus.REJECTED,
        PendingMatchStatus.EXPIRED,
    ]
    confidences = ["high", "medium", "low"]
    for index in range(needed):
        issue = _issue_at(issues, index + 20)
        status = statuses[index % len(statuses)]
        resolved_at = _ago(days=index // 3, minutes=index * 13)
        row = PendingMatch(
            issue_id=issue.id,
            release_title=f"{SEED_PREFIX} Intervention History {index + 1:03d}",
            download_url=f"https://seed.pullbox.local/intervention-history/{run_id}/{index}",
            is_torrent=bool((index + 1) % 2),
            file_size=65_000_000 + index * 900_000,
            confidence=confidences[index % len(confidences)],
            match_details={
                "series_match_type": "fuzzy" if index % 2 else "exact",
                "issue_match": status != PendingMatchStatus.REJECTED,
                "year_match": index % 4 != 0,
                "type_match": index % 5 != 0,
                "rejection_reason": "Synthetic resolved row for footer testing"
                if status == PendingMatchStatus.REJECTED
                else "",
                "indexer_name": "Footer Gap Seed Indexer",
            },
            status=status,
            resolved_at=resolved_at,
            resolved_by="seed",
        )
        _touch_timestamps(row, index + 240)
        session.add(row)
    return needed


async def _seed_search_history(session: AsyncSession, issues: list[Issue]) -> int:
    current = await _count_search_history(session)
    needed = max(0, TARGET_ROWS - current)
    search_types = [SearchType.MANUAL, SearchType.AUTOMATED, SearchType.BULK]
    confidences = ["high", "medium", "low", None]
    for index in range(needed):
        issue = _issue_at(issues, index + 50)
        row = SearchLog(
            issue_id=issue.id,
            series_title=f"{SEED_PREFIX} Series",
            issue_number=issue.issue_number,
            search_type=search_types[index % len(search_types)],
            results_found=12 + (index % 9),
            results_grabbed=1 if index % 6 == 0 else 0,
            results_queued=1 if index % 5 == 0 else 0,
            results_rejected=3 + (index % 7),
            results_blocklisted=index % 3,
            best_confidence=confidences[index % len(confidences)],
            details={
                "run_state": "completed",
                "seed": "footer-gap",
                "provider_count": 3,
            },
        )
        _touch_timestamps(row, index + 280)
        session.add(row)
    return needed


async def seed(session: AsyncSession) -> None:
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    issues = await _get_or_create_seed_issues(session)

    additions = {
        "downloads queue": await _seed_download_queue(session, issues, run_id),
        "downloads history": await _seed_download_history(session, issues, run_id),
        "post-processing queue": await _seed_post_processing_queue(session, issues, run_id),
        "post-processing history": await _seed_post_processing_history(session, issues, run_id),
        "blocklist": await _seed_blocklist(session, issues, run_id),
        "intervention queue": await _seed_intervention_queue(session, issues, run_id),
        "intervention history": await _seed_intervention_history(session, issues, run_id),
        "search history": await _seed_search_history(session, issues),
    }

    await session.commit()

    print("Footer gap seed complete.")
    for label, count in additions.items():
        print(f"  {label}: added {count}")

    print()
    print("Current page-bucket counts:")
    print(f"  downloads queue: {await _count_download_queue(session)}")
    print(f"  downloads active: {await _count_download_active(session)}")
    print(f"  downloads queued: {await _count_download_waiting(session)}")
    print(f"  downloads history: {await _count_download_history(session)}")
    print(f"  post-processing queue: {await _count_post_processing_queue(session)}")
    print(f"  post-processing history: {await _count_post_processing_history(session)}")
    print(f"  blocklist: {await _count_blocklist(session)}")
    print(f"  intervention queue: {await _count_intervention_queue(session)}")
    print(f"  intervention history: {await _count_intervention_history(session)}")
    print(f"  search history: {await _count_search_history(session)}")


async def main() -> None:
    settings = get_settings()
    db_url = settings.db_url
    if "sqlite" in db_url and "///" in db_url:
        Path(db_url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
