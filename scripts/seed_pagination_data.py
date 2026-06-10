"""Seed additional data to ensure ALL paginated views have enough records.

Supplements seed_full_dev_data.py by filling gaps in tables that don't
have enough records for pagination testing.

Idempotent: checks existing counts before adding.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_pagination_data.py
"""

import asyncio
import io
import json
import struct
import sys
import uuid
import zipfile
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.models.base import Base
from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title
from pullbox.models.import_job import (
    ImportedFile,
    ImportedSeries,
    ImportJob,
    ImportJobLog,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
    ImportedFileStatus,
)
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.matching_suggestion import MatchingSuggestion, SuggestionStatus
from pullbox.models.series import Series
from pullbox.models.issue import Issue, IssueStatus
from pullbox.utilities.models import (
    ItemState,
    JobState,
    JobType,
    LogLevel,
    UtilityJob,
    UtilityJobItem,
    UtilityJobLog,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_COMICS_DIR = _PROJECT_ROOT / "data" / "comics"


def _ago(days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days, hours=hours, minutes=minutes)


def _make_minimal_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    def _chunk(t: bytes, d: bytes) -> bytes:
        raw = t + d
        crc = struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
        return struct.pack(">I", len(d)) + raw + crc
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\x33\x33\x33"))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_dummy_cbz(page_count: int = 3) -> bytes:
    page_png = _make_minimal_png()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(page_count):
            zf.writestr(f"page_{i + 1:03d}.png", page_png)
    return buf.getvalue()


# ── Blocklist (needs 30+, currently 8) ──────────────────────────────


async def _seed_extra_blocklist(session: AsyncSession) -> int:
    count = (await session.execute(select(func.count(BlocklistEntry.id)))).scalar_one()
    if count >= 30:
        print(f"  Blocklist: already has {count} entries, skipping.")
        return 0

    series_ids = [r[0] for r in (await session.execute(select(Series.id).limit(10))).all()]
    issue_ids = [r[0] for r in (await session.execute(select(Issue.id).limit(20))).all()]
    indexer_ids = []
    try:
        from pullbox.models.indexer import IndexerConfig
        indexer_ids = [r[0] for r in (await session.execute(select(IndexerConfig.id).limit(5))).all()]
    except Exception:
        pass

    groups = ["Sketchy-Scans", "Low-Res-Rips", "Fakeout-Group", "Corrupt-Archive",
              "Wrong-Issue-Rls", "Bad-OCR-Crew", "Watermarked-Scans", "Duplicate-Upload",
              "Missing-Pages", "Re-encoded-Junk", "Troll-Upload", "Wrong-Series"]
    reasons = [BlocklistReason.FAILED, BlocklistReason.REJECTED, BlocklistReason.MANUAL]
    errors = [
        "Extraction failed: archive corrupted (CRC mismatch)",
        "File was not a valid comic archive",
        "User rejected: wrong issue inside archive",
        "Post-processing failed: name matcher returned no match",
        "Download failed: connection reset by peer",
        "Manually blocklisted: known low-quality group",
        "Archive contains watermarked pages",
        "Duplicate of already-owned issue",
        "Archive missing pages 5-12",
        "Re-encoded at 72dpi — unreadable text",
        "Troll upload: not a comic file",
        "Wrong series entirely — Batman instead of Batgirl",
    ]
    titles = [
        "Batman {n:03d} (2016) (Digital) ({grp}).cbz",
        "Amazing Spider-Man {n:03d} (2022) (Webrip) ({grp}).cbr",
        "Saga {n:03d} (2012) (Scan) ({grp}).cbz",
        "X-Men {n:03d} (2021) (Digital) ({grp}).cbz",
        "Superman {n:03d} (2023) (Digital) ({grp}).cbr",
        "Invincible {n:03d} (2003) (Scan) ({grp}).cbz",
        "Spawn {n:03d} (1992) (Digital) ({grp}).cbr",
        "Walking Dead {n:03d} (2003) (Webrip) ({grp}).cbz",
    ]

    needed = 35 - count
    added = 0
    for i in range(needed):
        grp = groups[i % len(groups)]
        title = titles[i % len(titles)].format(n=i + 10, grp=grp)
        entry = BlocklistEntry(
            release_title=title,
            release_title_normalized=normalize_release_title(title),
            download_url=f"https://indexer.example.com/dl/blocklist-{i}",
            series_id=series_ids[i % len(series_ids)] if series_ids else None,
            issue_id=issue_ids[i % len(issue_ids)] if issue_ids else None,
            indexer_id=indexer_ids[i % len(indexer_ids)] if indexer_ids else None,
            reason=reasons[i % len(reasons)],
            error_message=errors[i % len(errors)],
            release_group=grp,
        )
        entry.created_at = _ago(days=i * 2, hours=i % 12)  # type: ignore[assignment]
        session.add(entry)
        added += 1

    await session.flush()
    print(f"  Blocklist: added {added} entries (total now {count + added})")
    return added


# ── Matching Suggestions (needs 30+, currently 0) ───────────────────


async def _seed_matching_suggestions(session: AsyncSession) -> int:
    count = (await session.execute(select(func.count(MatchingSuggestion.id)))).scalar_one()
    if count >= 30:
        print(f"  Matching suggestions: already has {count}, skipping.")
        return 0

    # Need library_file_ids and series_ids
    lib_file_ids = [r[0] for r in (await session.execute(
        select(LibraryFile.id).where(LibraryFile.match_confidence == MatchConfidence.UNMATCHED).limit(50)
    )).all()]

    # If not enough unmatched files, use any files
    if len(lib_file_ids) < 30:
        lib_file_ids = [r[0] for r in (await session.execute(select(LibraryFile.id).limit(50))).all()]

    if not lib_file_ids:
        print("  Matching suggestions: no library files to link to, skipping.")
        return 0

    series_ids = [r[0] for r in (await session.execute(select(Series.id).limit(20))).all()]

    suggestion_data = [
        ("Batman Annual", 2017, "DC Comics", "annual", "filename", 0.85),
        ("Batman: White Knight", 2017, "DC Comics", "standard", "filename", 0.72),
        ("Amazing Spider-Man Annual", 2022, "Marvel", "annual", "filename", 0.88),
        ("Spider-Man: Life Story", 2019, "Marvel", "standard", "comicinfo", 0.65),
        ("Saga Compendium", 2019, "Image Comics", "compendium", "filename", 0.91),
        ("X-Men: Grand Design", 2017, "Marvel", "standard", "cv_title", 0.78),
        ("Superman: Son of Kal-El", 2021, "DC Comics", "standard", "filename", 0.82),
        ("Batman: Three Jokers", 2020, "DC Comics", "standard", "comicinfo", 0.69),
        ("Invincible Compendium", 2011, "Image Comics", "compendium", "filename", 0.94),
        ("Walking Dead Deluxe", 2020, "Image Comics", "deluxe", "filename", 0.87),
        ("Saga TPB Vol 1", 2012, "Image Comics", "tpb", "filename", 0.92),
        ("X-Men: Inferno", 2021, "Marvel", "standard", "cv_title", 0.71),
        ("Batman: Hush", 2002, "DC Comics", "tpb", "comicinfo", 0.84),
        ("Spider-Verse", 2014, "Marvel", "standard", "filename", 0.67),
        ("Superman: Red Son", 2003, "DC Comics", "standard", "comicinfo", 0.76),
        ("X-Men: Age of Apocalypse", 1995, "Marvel", "standard", "cv_title", 0.80),
        ("Saga: Book One", 2014, "Image Comics", "hardcover", "filename", 0.89),
        ("Batman Beyond", 2015, "DC Comics", "standard", "filename", 0.73),
        ("Amazing Spider-Man: Renew Your Vows", 2016, "Marvel", "standard", "cv_title", 0.68),
        ("Superman: Action Comics", 2016, "DC Comics", "standard", "filename", 0.77),
        ("X-Men: Marauders", 2019, "Marvel", "standard", "comicinfo", 0.74),
        ("Batman: Detective Comics", 2016, "DC Comics", "standard", "filename", 0.81),
        ("Spider-Man 2099", 2014, "Marvel", "standard", "cv_title", 0.70),
        ("Saga: The Complete Collection", 2024, "Image Comics", "omnibus", "filename", 0.95),
        ("Walking Dead: Here's Negan", 2017, "Image Comics", "graphic_novel", "comicinfo", 0.83),
        ("X-Men: Hellfire Gala", 2022, "Marvel", "one_shot", "filename", 0.66),
        ("Batman: The Long Halloween", 1996, "DC Comics", "tpb", "comicinfo", 0.90),
        ("Superman: Birthright", 2003, "DC Comics", "standard", "cv_title", 0.75),
        ("Invincible TPB Vol 2", 2004, "Image Comics", "tpb", "filename", 0.86),
        ("Spider-Man: Blue", 2002, "Marvel", "standard", "comicinfo", 0.79),
        ("Batman: Year One Deluxe", 1987, "DC Comics", "deluxe", "filename", 0.93),
        ("X-Men: Days of Future Past", 1981, "Marvel", "tpb", "comicinfo", 0.88),
        ("Saga Special Edition", 2023, "Image Comics", "special", "filename", 0.64),
        ("Amazing Spider-Man: Clone Conspiracy", 2016, "Marvel", "standard", "cv_title", 0.72),
        ("Superman: All-Star", 2005, "DC Comics", "standard", "comicinfo", 0.85),
    ]

    added = 0
    for i, (title, year, pub, stype, source, score) in enumerate(suggestion_data):
        if i >= len(lib_file_ids):
            break
        suggestion = MatchingSuggestion(
            library_file_id=lib_file_ids[i],
            parent_series_id=series_ids[i % len(series_ids)] if series_ids else None,
            suggested_comicvine_id=100000 + i,
            suggested_title=title,
            suggested_year=year,
            suggested_publisher=pub,
            suggested_series_type=stype,
            detection_source=source,
            confidence_score=score,
            reason=f"Detected as possible {stype} of existing series based on {source} analysis",
            status=SuggestionStatus.PENDING if i < 25 else SuggestionStatus.DISMISSED,
        )
        session.add(suggestion)
        added += 1

    await session.flush()
    print(f"  Matching suggestions: added {added} (25 pending, {max(0, added - 25)} dismissed)")
    return added


# ── Utility Jobs (needs 30+, currently 0) ───────────────────────────


async def _seed_utility_jobs(session: AsyncSession) -> int:
    count = (await session.execute(select(func.count()).select_from(UtilityJob))).scalar_one()
    if count >= 30:
        print(f"  Utility jobs: already has {count}, skipping.")
        return 0

    now = datetime.now(UTC)
    job_types = [
        (JobType.MASS_CONVERT_PIPELINE, "Mass Convert CBR→CBZ"),
        (JobType.MASS_RENAME, "Mass Rename Comics"),
        (JobType.INTEGRITY_CHECK, "File Integrity Check"),
        (JobType.DB_CHECK_CLEANUP, "Database Check & Cleanup"),
        (JobType.EXPORT_LIBRARY, "Export Library"),
    ]
    states = [JobState.COMPLETED, JobState.COMPLETED, JobState.COMPLETED,
              JobState.FAILED, JobState.COMPLETED, JobState.CANCELLED]

    added = 0
    for i in range(35):
        jtype, display = job_types[i % len(job_types)]
        state = states[i % len(states)]
        job_id = str(uuid.uuid4())
        created = (now - timedelta(days=35 - i, hours=i % 8)).isoformat()
        started = (now - timedelta(days=35 - i, hours=i % 8) + timedelta(seconds=2)).isoformat()
        completed = (now - timedelta(days=35 - i, hours=i % 8) + timedelta(minutes=2 + i % 5)).isoformat() if state != JobState.CANCELLED else None

        total = 20 + (i * 7) % 80
        completed_items = total if state == JobState.COMPLETED else (total // 3 if state == JobState.CANCELLED else total - 2)
        failed_items = 0 if state == JobState.COMPLETED else (2 if state == JobState.FAILED else 0)
        skipped_items = i % 5

        job = UtilityJob(
            id=job_id,
            job_type=jtype,
            display_name=f"{display} — batch {i + 1}",
            state=state,
            config=json.dumps({"dry_run": i % 4 == 0, "source": "/comics"}),
            total_items=total,
            completed_items=completed_items,
            failed_items=failed_items,
            skipped_items=skipped_items,
            warning_count=i % 3,
            created_at=created,
            started_at=started,
            completed_at=completed,
            error_message="Worker process crashed: out of memory" if state == JobState.FAILED else None,
            created_by="admin",
        )
        session.add(job)

        # Add items for each job (5-10 per job for detail page testing)
        item_count = min(8, total)
        for j in range(item_count):
            item_id = str(uuid.uuid4())
            item_state = ItemState.COMPLETED if j < item_count - 1 else (ItemState.FAILED if state == JobState.FAILED else ItemState.COMPLETED)
            item = UtilityJobItem(
                id=item_id,
                job_id=job_id,
                item_index=j,
                state=item_state,
                file_path=f"/comics/Series {i}/{display.split()[0]} #{j + 1:03d}.cbz",
                operation=jtype.split("_")[0] if "_" in jtype else jtype,
                before_state=json.dumps({"format": "cbr", "size": 15000000 + j * 1000}),
                after_state=json.dumps({"format": "cbz", "size": 14000000 + j * 900}) if item_state == ItemState.COMPLETED else "{}",
                started_at=(now - timedelta(days=35 - i) + timedelta(seconds=10 + j * 30)).isoformat(),
                completed_at=(now - timedelta(days=35 - i) + timedelta(seconds=40 + j * 30)).isoformat() if item_state == ItemState.COMPLETED else None,
                duration_ms=(25000 + j * 3000) if item_state == ItemState.COMPLETED else None,
                error_message="Failed to read archive: permission denied" if item_state == ItemState.FAILED else None,
            )
            session.add(item)

        # Add log entries per job
        for j in range(5):
            log = UtilityJobLog(
                job_id=job_id,
                timestamp=(now - timedelta(days=35 - i) + timedelta(seconds=j * 15)).isoformat(),
                level=[LogLevel.INFO, LogLevel.INFO, LogLevel.WARNING, LogLevel.INFO, LogLevel.INFO][j],
                message=[
                    f"Job started: processing {total} files",
                    "Scanning directory: /comics",
                    f"Skipped {skipped_items} files (already processed)",
                    f"Processed {completed_items}/{total} files",
                    f"Job {'completed successfully' if state == JobState.COMPLETED else 'finished with errors'}",
                ][j],
                file_path=f"/comics/Series {i}/" if j == 1 else None,
            )
            session.add(log)

        added += 1

    await session.flush()
    print(f"  Utility jobs: added {added} jobs with items and logs")
    return added


# ── Import Files + Logs (supplement import_jobs) ────────────────────


async def _seed_import_files_and_logs(session: AsyncSession) -> int:
    file_count = (await session.execute(select(func.count()).select_from(ImportedFile))).scalar_one()
    if file_count > 0:
        print(f"  Import files: already has {file_count}, skipping.")
        return 0

    # Get completed import jobs with imported series
    jobs = (await session.execute(
        select(ImportJob).where(ImportJob.status == ImportJobStatus.COMPLETED).limit(10)
    )).scalars().all()

    if not jobs:
        print("  Import files: no completed jobs found, skipping.")
        return 0

    # Get imported series linked to these jobs
    job_ids = [j.id for j in jobs]
    imp_series = (await session.execute(
        select(ImportedSeries).where(ImportedSeries.import_job_id.in_(job_ids)).limit(30)
    )).scalars().all()

    now = datetime.now(UTC)
    added_files = 0
    added_logs = 0

    for series in imp_series:
        # Add 3-5 files per imported series
        n_files = 3 + (series.id % 3)
        for j in range(n_files):
            status = ImportedFileStatus.IMPORTED if j < n_files - 1 else (
                ImportedFileStatus.NO_MATCH if series.id % 4 == 0 else ImportedFileStatus.IMPORTED
            )
            f = ImportedFile(
                import_job_id=series.import_job_id,
                imported_series_id=series.id,
                status=status,
                source_path=f"{series.source_folder}/{series.raw_series_name} #{j + 1:03d}.cbz",
                file_name=f"{series.raw_series_name} #{j + 1:03d}.cbz",
                file_size=15000000 + j * 2000000,
                file_format="cbz",
                parsed_series=series.raw_series_name,
                parsed_issue_number=float(j + 1),
                parsed_year=series.raw_year,
            )
            session.add(f)
            added_files += 1

    # Add log entries for the jobs
    for job in jobs:
        log_messages = [
            ("info", "scan_started", f"Scanning {job.source_path}"),
            ("info", "scan_complete", f"Found {job.scan_total_files} files in {job.scan_total_dirs} directories"),
            ("info", "match_started", "Starting ComicVine matching"),
            ("warning", "match_low_confidence", "3 series matched with confidence below 70%"),
            ("info", "match_complete", f"Matched {job.series_matched}/{job.series_found} series"),
            ("info", "import_started", "Beginning file import to library"),
            ("info", "import_progress", f"Imported {job.total_files_imported} files"),
            ("info", "import_complete", f"Import finished: {job.series_imported} series, {job.total_files_imported} files"),
        ]
        for k, (level, event, msg) in enumerate(log_messages):
            log = ImportJobLog(
                import_job_id=job.id,
                logged_at=now - timedelta(days=30, hours=-k),
                level=level,
                event=event,
                message=msg,
            )
            session.add(log)
            added_logs += 1

    await session.flush()
    print(f"  Import files: added {added_files} files, {added_logs} logs")
    return added_files + added_logs


# ── Extra comic files on disk ───────────────────────────────────────


async def _seed_extra_comic_files(session: AsyncSession) -> int:
    """Create CBZ files for series that don't have files on disk yet."""
    # Get library root
    root = (await session.execute(select(LibraryRoot).limit(1))).scalar_one_or_none()
    if not root:
        print("  Extra comic files: no library root found, skipping.")
        return 0

    # Find series that have owned issues but no library files
    series_with_files = (await session.execute(
        select(LibraryFile.parsed_series).distinct()
    )).scalars().all()

    all_series = (await session.execute(
        select(Series).where(Series.publisher_id.isnot(None))
    )).scalars().all()

    cbz_data = _make_dummy_cbz(page_count=3)
    now = datetime.now(UTC)
    added = 0

    for series in all_series:
        if series.title in series_with_files:
            continue

        year = series.year_start or "Unknown"
        folder_name = f"{series.title} ({year})"
        series_dir = _COMICS_DIR / folder_name
        series_dir.mkdir(parents=True, exist_ok=True)

        series.path = str(series_dir)
        series.library_root_id = root.id

        # Get owned issues
        owned = (await session.execute(
            select(Issue).where(Issue.series_id == series.id, Issue.status == IssueStatus.OWNED)
        )).scalars().all()

        for issue in owned:
            num = issue.issue_number
            num_str = f"{int(num):03d}" if num == int(num) else f"{num:06.1f}"
            ext = "cbz"
            filename = f"{series.title} ({year}) #{num_str}.{ext}"
            file_path = series_dir / filename

            if not file_path.exists():
                file_path.write_bytes(cbz_data)

            # Check if LibraryFile already exists for this path
            existing_lf = (await session.execute(
                select(LibraryFile.id).where(LibraryFile.file_path == str(file_path))
            )).scalar_one_or_none()
            if existing_lf:
                continue

            lib_file = LibraryFile(
                file_path=str(file_path),
                file_name=filename,
                file_size=len(cbz_data),
                file_format=FileFormat.CBZ,
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
            added += 1

    await session.flush()
    print(f"  Extra comic files: added {added} files on disk + LibraryFile records")
    return added


# ── Main ────────────────────────────────────────────────────────────


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.db_url)

    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        print("=" * 60)
        print("  Pullbox — Pagination Gap Filler Seed")
        print("=" * 60)
        print()

        bl = await _seed_extra_blocklist(session)
        ms = await _seed_matching_suggestions(session)
        uj = await _seed_utility_jobs(session)
        ifl = await _seed_import_files_and_logs(session)
        cf = await _seed_extra_comic_files(session)

        await session.commit()

        total = bl + ms + uj + ifl + cf
        print()
        if total == 0:
            print("All pagination gaps already filled.")
        else:
            print(f"Done: {bl} blocklist, {ms} suggestions, {uj} utility jobs, {ifl} import files/logs, {cf} extra comic files")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
