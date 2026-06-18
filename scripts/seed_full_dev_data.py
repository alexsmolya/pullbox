"""Comprehensive seed — populate ALL feature areas with realistic test data.

Builds on seed_dev_data.py (minimal seed) by adding data for every feature page:
downloads, blocklist, search logs, pending matches, audit logs, and dummy comic
files on disk with corresponding LibraryFile records.

Idempotent: safe to run multiple times. Existing records are skipped.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_full_dev_data.py
"""

import asyncio
import io
import json
import struct
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the project root is on sys.path so pullbox is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Import and run the minimal seed first
from seed_dev_data import seed as seed_minimal

from pullbox.config import get_settings
from pullbox.models.audit_log import AuditEventType, AuditLog
from pullbox.models.base import Base
from pullbox.models.blocklist import (
    BlocklistEntry,
    BlocklistReason,
    normalize_release_title,
)
from pullbox.models.config import SystemConfig
from pullbox.models.download import (
    DownloadClientType,
    DownloadHistory,
    DownloadState,
)
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import (
    FileFormat,
    LibraryFile,
    LibraryRoot,
    MatchConfidence,
)
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series

# Resolve paths relative to project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_COMICS_DIR = _PROJECT_ROOT / "data" / "comics"


# ── Helpers ──────────────────────────────────────────────────────────


def _ago(days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    """Return a UTC datetime offset from now."""
    return datetime.now(UTC) - timedelta(days=days, hours=hours, minutes=minutes)


async def _get_issue_ids(session: AsyncSession) -> dict[str, int]:
    """Get issue IDs by 'series_title #number' key."""
    result = await session.execute(
        select(Issue.id, Series.title, Issue.issue_number).join(
            Series, Issue.series_id == Series.id
        )
    )
    return {f"{title} #{num}": id_ for id_, title, num in result.all()}


async def _get_series_ids(session: AsyncSession) -> dict[str, int]:
    """Get series IDs by title."""
    result = await session.execute(select(Series.id, Series.title))
    return {title: id_ for id_, title in result.all()}


async def _get_indexer_id(session: AsyncSession) -> int | None:
    """Get the sample indexer ID."""
    from pullbox.models.indexer import IndexerConfig

    result = await session.execute(select(IndexerConfig.id).limit(1))
    return result.scalar_one_or_none()


# ── Download History ─────────────────────────────────────────────────


async def _seed_download_history(session: AsyncSession) -> int:
    """Seed download history records across multiple states."""
    issues = await _get_issue_ids(session)
    indexer_id = await _get_indexer_id(session)

    existing = (await session.execute(select(DownloadHistory.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Download history already exists, skipping.")
        return 0

    now = datetime.now(UTC)
    records = [
        DownloadHistory(
            issue_id=issues["Batman #1.0"],
            indexer_id=indexer_id,
            title="Batman 001 (2016) (Digital) (Zone-Empire).cbz",
            download_url="https://indexer.example.com/dl/batman-001",
            download_client=DownloadClientType.SABNZBD,
            external_id="SABnzbd_nzo_abc123",
            state=DownloadState.IMPORTED,
            file_size=145_000_000,
            downloaded_path="/data/tmp/batman-001.cbz",
            final_path="/comics/Batman (2016)/Batman (2016) #001.cbz",
            sent_at=_ago(days=5, hours=2),
            completed_at=_ago(days=5, hours=1, minutes=45),
            imported_at=_ago(days=5, hours=1, minutes=44),
        ),
        DownloadHistory(
            issue_id=issues["Batman #2.0"],
            indexer_id=indexer_id,
            title="Batman 002 (2016) (Digital) (Zone-Empire).cbz",
            download_url="https://indexer.example.com/dl/batman-002",
            download_client=DownloadClientType.SABNZBD,
            external_id="SABnzbd_nzo_abc124",
            state=DownloadState.IMPORTED,
            file_size=138_000_000,
            downloaded_path="/data/tmp/batman-002.cbz",
            final_path="/comics/Batman (2016)/Batman (2016) #002.cbz",
            sent_at=_ago(days=5, hours=1, minutes=30),
            completed_at=_ago(days=5, hours=1, minutes=15),
            imported_at=_ago(days=5, hours=1, minutes=14),
        ),
        DownloadHistory(
            issue_id=issues["The Amazing Spider-Man #1.0"],
            indexer_id=indexer_id,
            title="Amazing Spider-Man 001 (2022) (Digital) (Shan-Empire).cbz",
            download_url="https://indexer.example.com/dl/asm-001",
            download_client=DownloadClientType.QBITTORRENT,
            external_id="qbt_hash_def456",
            state=DownloadState.IMPORTED,
            file_size=162_000_000,
            downloaded_path="/data/tmp/asm-001.cbz",
            final_path=(
                "/comics/The Amazing Spider-Man (2022)/The Amazing Spider-Man (2022) #001.cbz"
            ),
            sent_at=_ago(days=3, hours=6),
            completed_at=_ago(days=3, hours=4),
            imported_at=_ago(days=3, hours=3, minutes=59),
        ),
        DownloadHistory(
            issue_id=issues["Saga #1.0"],
            indexer_id=indexer_id,
            title="Saga 001 (2012) (Digital) (Nahkan-Empire).cbz",
            download_url="https://indexer.example.com/dl/saga-001",
            download_client=DownloadClientType.SABNZBD,
            external_id="SABnzbd_nzo_ghi789",
            state=DownloadState.IMPORTED,
            file_size=95_000_000,
            downloaded_path="/data/tmp/saga-001.cbz",
            final_path="/comics/Saga (2012)/Saga (2012) #001.cbz",
            sent_at=_ago(days=2),
            completed_at=_ago(days=1, hours=23),
            imported_at=_ago(days=1, hours=22, minutes=59),
        ),
        DownloadHistory(
            issue_id=issues["The Amazing Spider-Man #25.0"],
            indexer_id=indexer_id,
            title="Amazing Spider-Man 025 (2023) (Digital) (Zone-Empire).cbz",
            download_url="https://indexer.example.com/dl/asm-025",
            download_client=DownloadClientType.SABNZBD,
            external_id="SABnzbd_nzo_jkl012",
            state=DownloadState.DOWNLOADING,
            file_size=210_000_000,
            sent_at=_ago(minutes=15),
        ),
        DownloadHistory(
            issue_id=issues["Batman #3.0"],
            indexer_id=indexer_id,
            title="Batman 003 (2016) (Digital) (Zone-Empire).cbz",
            download_url="https://indexer.example.com/dl/batman-003",
            download_client=DownloadClientType.SABNZBD,
            external_id="SABnzbd_nzo_mno345",
            state=DownloadState.QUEUED,
            file_size=141_000_000,
        ),
        DownloadHistory(
            issue_id=issues["Saga #55.0"],
            indexer_id=indexer_id,
            title="Saga 055 (2022) (Webrip) (Sketchy-Group).cbr",
            download_url="https://indexer.example.com/dl/saga-055-bad",
            download_client=DownloadClientType.QBITTORRENT,
            external_id="qbt_hash_fail01",
            state=DownloadState.FAILED,
            file_size=88_000_000,
            error_message="Extraction failed: archive corrupted (CRC mismatch on page 12)",
            retry_count=3,
            max_retries=3,
            sent_at=_ago(days=1, hours=3),
            completed_at=_ago(days=1, hours=2),
        ),
        DownloadHistory(
            issue_id=issues["X-Men #10.0"],
            indexer_id=indexer_id,
            title="X-Men 010 (2022) (Digital) (Shan-Empire).cbz",
            download_url="https://indexer.example.com/dl/xmen-010",
            download_client=DownloadClientType.TRANSMISSION,
            external_id="transmission_hash_retry01",
            state=DownloadState.RETRY_PENDING,
            file_size=152_000_000,
            error_message="Connection timed out after 300s",
            retry_count=1,
            max_retries=3,
            next_retry_at=now + timedelta(minutes=30),
            sent_at=_ago(hours=2),
        ),
    ]

    for record in records:
        session.add(record)
    await session.flush()
    count = len(records)
    print(f"  Created {count} download history records")
    return count


# ── Blocklist Entries ────────────────────────────────────────────────


async def _seed_blocklist(session: AsyncSession) -> int:
    """Seed blocklist entries for the blocklist page."""
    series = await _get_series_ids(session)
    issues = await _get_issue_ids(session)

    existing = (await session.execute(select(BlocklistEntry.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Blocklist entries already exist, skipping.")
        return 0

    entries_data = [
        {
            "release_title": "Saga 055 (2022) (Webrip) (Sketchy-Group).cbr",
            "download_url": "https://indexer.example.com/dl/saga-055-bad",
            "series_id": series.get("Saga"),
            "issue_id": issues.get("Saga #55.0"),
            "reason": BlocklistReason.FAILED,
            "error_message": "Extraction failed: archive corrupted (CRC mismatch on page 12)",
            "release_group": "Sketchy-Group",
        },
        {
            "release_title": "Batman 050 (2018) (Webrip) (Fakeout-Scans).cbr",
            "download_url": "https://indexer.example.com/dl/batman-050-fake",
            "series_id": series.get("Batman"),
            "issue_id": issues.get("Batman #50.0"),
            "reason": BlocklistReason.FAILED,
            "error_message": "File was not a valid comic archive (PDF disguised as CBR)",
            "release_group": "Fakeout-Scans",
        },
        {
            "release_title": "Amazing Spider-Man 003 (2022) (Digital) (Wrong-Issue-Group).cbz",
            "download_url": "https://indexer.example.com/dl/asm-003-wrong",
            "series_id": series.get("The Amazing Spider-Man"),
            "issue_id": issues.get("The Amazing Spider-Man #3.0"),
            "reason": BlocklistReason.REJECTED,
            "error_message": "User rejected: wrong issue (contained #4 not #3)",
        },
        {
            "release_title": "X-Men 001 (2021) (Digital) (Low-Res-Rips).cbz",
            "download_url": "https://indexer.example.com/dl/xmen-001-lowres",
            "series_id": series.get("X-Men"),
            "issue_id": issues.get("X-Men #1.0"),
            "reason": BlocklistReason.MANUAL,
            "error_message": "Manually blocklisted: known low-quality release group",
            "release_group": "Low-Res-Rips",
        },
        {
            "release_title": "Saga 002 (2012) (Scan) (NOGRP).cbr",
            "download_url": "https://indexer.example.com/dl/saga-002-nogrp",
            "series_id": series.get("Saga"),
            "issue_id": issues.get("Saga #2.0"),
            "reason": BlocklistReason.FAILED,
            "error_message": "Post-processing failed: name matcher returned no match",
        },
    ]

    count = 0
    for data in entries_data:
        title = data["release_title"]
        entry = BlocklistEntry(
            release_title_normalized=normalize_release_title(title),
            **data,
        )
        session.add(entry)
        count += 1
        print(f"  Created blocklist entry: {title[:60]}...")

    await session.flush()
    return count


# ── Search Logs ──────────────────────────────────────────────────────


async def _seed_search_logs(session: AsyncSession) -> int:
    """Seed search log records for the search history page."""
    issues = await _get_issue_ids(session)

    existing = (await session.execute(select(SearchLog.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Search logs already exist, skipping.")
        return 0

    logs = [
        SearchLog(
            issue_id=issues["Batman #3.0"],
            series_title="Batman",
            issue_number=3.0,
            search_type=SearchType.AUTOMATED,
            results_found=8,
            results_grabbed=1,
            results_rejected=2,
            results_blocklisted=1,
            best_confidence="high",
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 1250},
            created_at=_ago(hours=6),
        ),
        SearchLog(
            issue_id=issues["The Amazing Spider-Man #3.0"],
            series_title="The Amazing Spider-Man",
            issue_number=3.0,
            search_type=SearchType.AUTOMATED,
            results_found=12,
            results_grabbed=0,
            results_queued=2,
            results_rejected=6,
            best_confidence="medium",
            details={"indexers_queried": ["NZBgeek", "DrunkenSlug"], "duration_ms": 2100},
            created_at=_ago(hours=6),
        ),
        SearchLog(
            issue_id=issues["Saga #55.0"],
            series_title="Saga",
            issue_number=55.0,
            search_type=SearchType.AUTOMATED,
            results_found=3,
            results_grabbed=0,
            results_rejected=3,
            best_confidence="low",
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 890},
            created_at=_ago(hours=6),
        ),
        SearchLog(
            issue_id=issues["X-Men #10.0"],
            series_title="X-Men",
            issue_number=10.0,
            search_type=SearchType.AUTOMATED,
            results_found=0,
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 750},
            created_at=_ago(hours=6),
        ),
        SearchLog(
            issue_id=issues["Batman #50.0"],
            series_title="Batman",
            issue_number=50.0,
            search_type=SearchType.MANUAL,
            results_found=15,
            results_grabbed=1,
            results_rejected=4,
            results_blocklisted=2,
            best_confidence="high",
            details={"indexers_queried": ["NZBgeek", "DrunkenSlug"], "duration_ms": 1800},
            created_at=_ago(days=2, hours=3),
        ),
        SearchLog(
            issue_id=issues["Saga #1.0"],
            series_title="Saga",
            issue_number=1.0,
            search_type=SearchType.MANUAL,
            results_found=22,
            results_grabbed=1,
            results_rejected=8,
            best_confidence="high",
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 1500},
            created_at=_ago(days=3, hours=1),
        ),
        SearchLog(
            issue_id=issues["The Amazing Spider-Man #25.0"],
            series_title="The Amazing Spider-Man",
            issue_number=25.0,
            search_type=SearchType.BULK,
            results_found=6,
            results_grabbed=1,
            results_queued=1,
            best_confidence="high",
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 980, "bulk_total": 5},
            created_at=_ago(days=1),
        ),
        SearchLog(
            issue_id=issues["X-Men #35.0"],
            series_title="X-Men",
            issue_number=35.0,
            search_type=SearchType.AUTOMATED,
            results_found=0,
            details={"indexers_queried": ["NZBgeek"], "duration_ms": 620},
            created_at=_ago(hours=1),
        ),
    ]

    for log in logs:
        session.add(log)
    await session.flush()
    count = len(logs)
    print(f"  Created {count} search log records")
    return count


# ── Pending Matches (Intervention Queue) ─────────────────────────────


async def _seed_pending_matches(session: AsyncSession) -> int:
    """Seed pending matches for the intervention queue page."""
    issues = await _get_issue_ids(session)

    existing = (await session.execute(select(PendingMatch.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Pending matches already exist, skipping.")
        return 0

    matches = [
        PendingMatch(
            issue_id=issues["The Amazing Spider-Man #3.0"],
            release_title="Amazing Spider-Man 003 (2022) (Digital) (Zone-Empire).cbz",
            download_url="https://indexer.example.com/dl/asm-003-zone",
            is_torrent=False,
            file_size=155_000_000,
            confidence="medium",
            match_details={
                "parsed_series": "Amazing Spider-Man",
                "parsed_issue": 3.0,
                "parsed_year": 2022,
                "series_similarity": 0.92,
                "reason": "Series title similarity below high threshold (0.92 < 0.95)",
            },
            status=PendingMatchStatus.PENDING,
        ),
        PendingMatch(
            issue_id=issues["The Amazing Spider-Man #3.0"],
            release_title="Amazing Spider-Man v6 003 (2022) (Webrip) (Shan-Empire).cbz",
            download_url="https://indexer.example.com/dl/asm-003-shan",
            is_torrent=True,
            file_size=142_000_000,
            confidence="medium",
            match_details={
                "parsed_series": "Amazing Spider-Man v6",
                "parsed_issue": 3.0,
                "parsed_year": 2022,
                "series_similarity": 0.88,
                "reason": "Volume suffix 'v6' not in series title",
            },
            status=PendingMatchStatus.PENDING,
        ),
        PendingMatch(
            issue_id=issues["Saga #55.0"],
            release_title="Saga 055 (2022) (Digital-Empire).cbz",
            download_url="https://indexer.example.com/dl/saga-055-dig",
            is_torrent=False,
            file_size=89_000_000,
            confidence="low",
            match_details={
                "parsed_series": "Saga",
                "parsed_issue": 55.0,
                "parsed_year": 2022,
                "series_similarity": 1.0,
                "reason": "File size unusually small for this series (avg 140MB)",
            },
            status=PendingMatchStatus.PENDING,
        ),
        PendingMatch(
            issue_id=issues["X-Men #10.0"],
            release_title="X-Men 010 (2022) (Digital) (Minutemen-Midas).cbz",
            download_url="https://indexer.example.com/dl/xmen-010-mm",
            is_torrent=False,
            file_size=175_000_000,
            confidence="medium",
            match_details={
                "parsed_series": "X-Men",
                "parsed_issue": 10.0,
                "parsed_year": 2022,
                "series_similarity": 1.0,
                "reason": "Year 2022 is outside series year range (2021)",
            },
            status=PendingMatchStatus.PENDING,
        ),
    ]

    for match in matches:
        session.add(match)
    await session.flush()
    count = len(matches)
    print(f"  Created {count} pending matches (intervention queue)")
    return count


# ── Audit Logs ───────────────────────────────────────────────────────


async def _seed_audit_logs(session: AsyncSession) -> int:
    """Seed audit log records for the security/audit page."""
    existing = (await session.execute(select(AuditLog.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Audit logs already exist, skipping.")
        return 0

    logs = [
        AuditLog(
            event_type=AuditEventType.LOGIN_SUCCESS,
            timestamp=_ago(hours=1),
            source_ip="192.168.1.100",
            user_id=1,
            username="admin",
            detail="Successful login",
        ),
        AuditLog(
            event_type=AuditEventType.LOGIN_FAILURE,
            timestamp=_ago(days=1, hours=5),
            source_ip="192.168.1.105",
            username="admin",
            detail="Invalid password (attempt 1/5)",
        ),
        AuditLog(
            event_type=AuditEventType.LOGIN_FAILURE,
            timestamp=_ago(days=1, hours=5),
            source_ip="192.168.1.105",
            username="admin",
            detail="Invalid password (attempt 2/5)",
        ),
        AuditLog(
            event_type=AuditEventType.LOGIN_SUCCESS,
            timestamp=_ago(days=1, hours=4),
            source_ip="192.168.1.105",
            user_id=1,
            username="admin",
            detail="Successful login after 2 failed attempts",
        ),
        AuditLog(
            event_type=AuditEventType.PASSWORD_CHANGED,
            timestamp=_ago(days=3),
            source_ip="192.168.1.100",
            user_id=1,
            username="admin",
            detail="Password changed successfully",
        ),
        AuditLog(
            event_type=AuditEventType.SECURITY_CONFIG_CHANGED,
            timestamp=_ago(days=5),
            source_ip="192.168.1.100",
            user_id=1,
            username="admin",
            detail="Changed session_lifetime_hours from 24 to 48",
            metadata_json=json.dumps(
                {"key": "session_lifetime_hours", "old_value": "24", "new_value": "48"}
            ),
        ),
        AuditLog(
            event_type=AuditEventType.LOGIN_SUCCESS,
            timestamp=_ago(days=7),
            source_ip="10.0.0.50",
            user_id=1,
            username="admin",
            detail="Successful login (Tailscale)",
        ),
    ]

    for log in logs:
        session.add(log)
    await session.flush()
    count = len(logs)
    print(f"  Created {count} audit log records")
    return count


# ── Dummy Comic Files + Library Records ──────────────────────────────


def _make_minimal_png() -> bytes:
    """Generate a minimal valid 1x1 pixel dark-gray PNG (~67 bytes)."""
    import zlib

    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        raw = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + raw + crc

    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw_row = b"\x00\x33\x33\x33"  # filter=none, R=51 G=51 B=51
    idat = _chunk(b"IDAT", zlib.compress(raw_row))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_dummy_cbz(page_count: int = 3) -> bytes:
    """Create a minimal valid CBZ file (ZIP with placeholder page PNGs)."""
    page_png = _make_minimal_png()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(page_count):
            zf.writestr(f"page_{i + 1:03d}.png", page_png)
    return buf.getvalue()


def _make_dummy_cbr() -> bytes:
    """Create a minimal file with .cbr extension.

    Uses ZIP format internally (not RAR) since creating real RAR archives
    requires the rar command-line tool. The integrity checker will flag
    this as a format mismatch — which is actually useful test data.
    """
    return _make_dummy_cbz(page_count=2)


async def _seed_comic_files(session: AsyncSession) -> int:
    """Create dummy comic files on disk with linked LibraryFile records.

    Creates series folders under the local comics library root, writes minimal CBZ/CBR
    files for issues with OWNED status, updates series.path, and creates
    LibraryFile records linked to issues.
    """
    existing = (await session.execute(select(LibraryFile.id).limit(1))).scalar_one_or_none()
    if existing:
        print("  Library files already exist, skipping.")
        return 0

    # Get or update library root to point to local comics dir
    comics_path = str(_COMICS_DIR)
    root = (
        await session.execute(select(LibraryRoot).where(LibraryRoot.path == "/comics"))
    ).scalar_one_or_none()

    if root:
        root.path = comics_path
        root.name = "Comics Library"
    else:
        root = (
            await session.execute(select(LibraryRoot).where(LibraryRoot.path == comics_path))
        ).scalar_one_or_none()
        if not root:
            root = LibraryRoot(name="Comics Library", path=comics_path)
            session.add(root)
    await session.flush()

    # Get all series with publishers (= from the seed, not empty orphans)
    result = await session.execute(select(Series).where(Series.publisher_id.isnot(None)))
    all_series = list(result.scalars().all())

    cbz_data = _make_dummy_cbz(page_count=3)
    cbr_data = _make_dummy_cbr()
    now = datetime.now(UTC)
    count = 0

    for series in all_series:
        year = series.year_start or "Unknown"
        folder_name = f"{series.title} ({year})"
        series_dir = _COMICS_DIR / folder_name
        series_dir.mkdir(parents=True, exist_ok=True)

        # Update series record with local path and library root
        series.path = str(series_dir)
        series.library_root_id = root.id

        # Get owned issues for this series
        issues_result = await session.execute(
            select(Issue).where(
                Issue.series_id == series.id,
                Issue.status == IssueStatus.OWNED,
            )
        )
        owned_issues = list(issues_result.scalars().all())

        for issue in owned_issues:
            num = issue.issue_number
            num_str = f"{int(num):03d}" if num == int(num) else f"{num:06.1f}"

            # Every 5th file is CBR for variety
            if count % 5 == 3:
                ext = "cbr"
                file_data = cbr_data
                file_format = FileFormat.CBR
            else:
                ext = "cbz"
                file_data = cbz_data
                file_format = FileFormat.CBZ

            filename = f"{series.title} ({year}) #{num_str}.{ext}"
            file_path = series_dir / filename

            if not file_path.exists():
                file_path.write_bytes(file_data)

            lib_file = LibraryFile(
                file_path=str(file_path),
                file_name=filename,
                file_size=len(file_data),
                file_format=file_format,
                file_modified_at=now,
                match_confidence=MatchConfidence.HIGH,
                parsed_series=series.title,
                parsed_issue_number=issue.issue_number,
                parsed_year=series.year_start,
                has_comicinfo=False,
                issue_id=issue.id,
                library_root_id=root.id,
            )
            session.add(lib_file)
            count += 1
            print(f"  Created file: {filename}")

    await session.flush()
    return count


# ── SystemConfig Local Dev Overrides ─────────────────────────────────


async def _seed_local_dev_config(session: AsyncSession) -> int:
    """Update SystemConfig values for local development paths.

    Overrides the Docker-default absolute paths (/data/*) with paths
    pointing to data/ under the project root.
    """
    overrides = {
        "comics_directory": str(_COMICS_DIR),
        "logs_dir": str(_PROJECT_ROOT / "data" / "logs"),
        "backup_dir": str(_PROJECT_ROOT / "data" / "backups"),
    }

    count = 0
    for key, value in overrides.items():
        row = await session.get(SystemConfig, key)
        if row:
            if row.value != value:
                row.value = value
                count += 1
                print(f"  Updated SystemConfig: {key} = {value}")
            else:
                print(f"  SystemConfig '{key}' already set, skipping.")
        else:
            session.add(SystemConfig(key=key, value=value, value_type="string"))
            count += 1
            print(f"  Created SystemConfig: {key} = {value}")

    await session.flush()
    return count


# ── Main ─────────────────────────────────────────────────────────────


async def seed_full(session: AsyncSession) -> None:
    """Run minimal seed, then add comprehensive data for every feature area."""
    # Step 1: Minimal seed (publishers, series, issues, admin user, config)
    await seed_minimal(session)
    print()

    # Step 2: Override SystemConfig for local dev paths
    print("Configuring local development paths...")
    cfg_count = await _seed_local_dev_config(session)
    print()

    # Step 3: Feature data for every page
    print("Seeding comprehensive feature data...")
    print()
    dl_count = await _seed_download_history(session)
    bl_count = await _seed_blocklist(session)
    sl_count = await _seed_search_logs(session)
    pm_count = await _seed_pending_matches(session)
    al_count = await _seed_audit_logs(session)
    print()

    # Step 4: Dummy comic files + library records
    print("Creating dummy comic files...")
    files_count = await _seed_comic_files(session)

    await session.commit()

    total = dl_count + bl_count + sl_count + pm_count + al_count + files_count + cfg_count
    print()
    if total == 0:
        print("Full seed data already exists, nothing new created.")
    else:
        print(
            f"Full seed complete: {files_count} comic files, {dl_count} downloads, "
            f"{bl_count} blocklist entries, {sl_count} search logs, "
            f"{pm_count} pending matches, {al_count} audit logs, "
            f"{cfg_count} config overrides."
        )
    print()
    print("Login credentials: admin / pullbox")
    print("Dev server: make run  →  http://localhost:8585")
    print()
    print("Info: ComicVine: To fetch real metadata + covers, set PULLBOX_COMICVINE_API_KEY")
    print("   in your .env file, then trigger a metadata refresh from the UI.")


async def main() -> None:
    """Create tables (if needed) and seed comprehensive data."""
    settings = get_settings()

    db_url = settings.db_url
    if "sqlite" in db_url:
        db_path = db_url.split("///", 1)[-1] if "///" in db_url else None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Ensure the standard data directory structure exists.
    data_root = _PROJECT_ROOT / "data"
    for subdir in ("backups", "comics", "logs", "tmp"):
        (data_root / subdir).mkdir(parents=True, exist_ok=True)
    (data_root / "comics" / ".covers").mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        print("=" * 60)
        print("  Pullbox — Full Development Seed")
        print("=" * 60)
        print()
        await seed_full(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
