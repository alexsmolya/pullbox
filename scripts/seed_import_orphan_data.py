"""Seed import history + orphaned series data for visual testing.

Creates enough records to trigger pagination on both pages.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_import_orphan_data.py
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.models.base import Base
from pullbox.models.import_job import (
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)


async def _seed_import_jobs(session: AsyncSession) -> int:
    """Create 60+ import jobs for pagination on /import/history (50 per page)."""
    existing = (await session.execute(select(ImportJob).limit(1))).scalar_one_or_none()
    if existing:
        print("  Import jobs already exist, skipping.")
        return 0

    now = datetime.now(UTC)
    jobs_data = []

    # Mix of completed, failed, and cancelled jobs with realistic data
    source_paths = [
        "/mnt/nas/comics/collection-2024",
        "/mnt/nas/comics/dc-backlog",
        "/mnt/nas/comics/marvel-collection",
        "/mnt/nas/comics/image-vault",
        "/home/user/Downloads/comics-batch",
        "/mnt/nas/comics/indie-publishers",
        "/mnt/nas/comics/vertigo-complete",
        "/mnt/nas/comics/dark-horse-runs",
        "/mnt/nas/comics/boom-studios",
        "/mnt/nas/comics/idw-collection",
        "/mnt/nas/comics/valiant-universe",
        "/mnt/nas/comics/aftershock-titles",
    ]

    for i in range(65):
        age_days = 65 - i  # oldest first
        created = now - timedelta(days=age_days, hours=i % 12, minutes=i * 7 % 60)

        # Vary statuses: mostly completed, some failed, a few cancelled
        if i % 10 == 7:
            status = ImportJobStatus.FAILED
            error_msg = [
                "Connection timeout reading /mnt/nas/comics",
                "Permission denied: /mnt/nas/comics/restricted",
                "Disk full during file copy phase",
                "ComicVine API rate limit exceeded after 450 requests",
                "Database lock timeout during bulk insert",
            ][i % 5]
            series_found = (i * 3 + 5) % 40
            series_imported = 0
            series_failed = series_found
            files_found = series_found * 12
            files_imported = 0
        elif i % 15 == 13:
            status = ImportJobStatus.CANCELLED
            error_msg = None
            series_found = (i * 4 + 8) % 50
            series_imported = series_found // 3
            series_failed = 0
            files_found = series_found * 10
            files_imported = series_imported * 8
        else:
            status = ImportJobStatus.COMPLETED
            error_msg = None
            series_found = (i * 3 + 7) % 45 + 3
            series_matched = int(series_found * 0.85)
            series_imported = series_matched
            series_failed = 0
            files_found = series_found * (8 + i % 5)
            files_imported = int(files_found * 0.9)

        scan_started = created + timedelta(seconds=2)
        scan_done = scan_started + timedelta(seconds=15 + i % 30)
        match_started = scan_done + timedelta(seconds=1)
        match_done = match_started + timedelta(seconds=30 + i * 2 % 60)
        import_started = match_done + timedelta(seconds=5)
        import_done = (
            import_started + timedelta(minutes=1 + i % 5)
            if status == ImportJobStatus.COMPLETED
            else None
        )

        job = ImportJob(
            source_path=source_paths[i % len(source_paths)],
            source_type=ImportSourceType.FILESYSTEM,
            status=status,
            scan_total_files=files_found + (i % 20),
            scan_total_dirs=(series_found + 2),
            series_found=series_found,
            series_matched=int(series_found * 0.85) if status != ImportJobStatus.FAILED else 0,
            series_no_match=series_found - int(series_found * 0.85)
            if status != ImportJobStatus.FAILED
            else series_found,
            series_new=0,
            series_duplicate=i % 3,
            series_imported=series_imported if status != ImportJobStatus.FAILED else 0,
            series_failed=series_failed if status == ImportJobStatus.FAILED else i % 2,
            total_files_found=files_found,
            total_files_matched=int(files_found * 0.9) if status != ImportJobStatus.FAILED else 0,
            total_files_conflict=i % 4,
            total_files_no_match=int(files_found * 0.1)
            if status != ImportJobStatus.FAILED
            else files_found,
            total_files_imported=files_imported if status != ImportJobStatus.FAILED else 0,
            total_files_failed=0 if status == ImportJobStatus.COMPLETED else files_found,
            scan_started_at=scan_started,
            scan_completed_at=scan_done,
            match_started_at=match_started,
            match_completed_at=match_done,
            import_started_at=import_started,
            import_completed_at=import_done,
            error_message=error_msg,
            monitored=True,
            search_on_add=i % 3 != 0,
            move_to_library=True,
            cv_match_threshold=0.70,
            auto_accept_high_confidence=True,
            skip_no_match=False,
            min_files_per_series=1,
        )
        # Manually set created_at for realistic dates
        job.created_at = created  # type: ignore[assignment]
        jobs_data.append(job)

    session.add_all(jobs_data)
    await session.flush()
    print(f"  Created {len(jobs_data)} import jobs")
    return len(jobs_data)


async def _seed_orphaned_series(session: AsyncSession) -> int:
    """Create 40+ orphaned (NO_MATCH) + 20+ dismissed (SKIPPED) ImportedSeries.

    These must belong to COMPLETED import jobs for the orphaned page to show them.
    """
    existing = (
        await session.execute(
            select(ImportedSeries)
            .where(
                ImportedSeries.status.in_([ImportSeriesStatus.NO_MATCH, ImportSeriesStatus.SKIPPED])
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        print("  Orphaned series already exist, skipping.")
        return 0

    # Get completed import jobs to attach orphaned series to
    completed_jobs = (
        (
            await session.execute(
                select(ImportJob)
                .where(ImportJob.status == ImportJobStatus.COMPLETED)
                .order_by(ImportJob.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    if not completed_jobs:
        print("  No completed import jobs found. Run import job seed first.")
        return 0

    orphan_names = [
        # DC-ish
        "Green Lantern - Emerald Dawn",
        "Hawkman Chronicles",
        "Justice Society of America - The Golden Age",
        "Batgirl and the Birds of Prey",
        "Blue Beetle - Jaime Reyes",
        "Doom Patrol - Weight of the Worlds",
        "Swamp Thing - New Roots",
        "Constantine - The Hellblazer Returns",
        "Starman - Times Past",
        "Legion of Super-Heroes - Great Darkness",
        "Zatanna - Mistress of Magic",
        "Plastic Man - Stretching the Truth",
        "The Question - Urban Renewal",
        "Animal Man - The Hunt",
        "Booster Gold - 52 Pickup",
        # Marvel-ish
        "Silver Surfer - Parable",
        "Moon Knight - Midnight Mission",
        "She-Hulk - Law and Disorder",
        "Blade - Vampire Hunter",
        "Ghost Rider - Road to Damnation",
        "Nova - The Human Rocket",
        "Thunderbolts - Justice Like Lightning",
        "Black Panther - A Nation Under Our Feet",
        "Captain Britain - The Crooked World",
        "Power Pack - Day One",
        "Runaways - Pride and Joy",
        "New Warriors - Reality Check",
        "Agents of Atlas - Dark Reign",
        "Shang-Chi - Brothers and Sisters",
        "Darkhawk - Heart of the Hawk",
        # Indie-ish
        "Bone - Out from Boneville",
        "Usagi Yojimbo - Grasscutter",
        "Concrete - Think Like a Mountain",
        "Strangers in Paradise - Abstract Edition",
        "Love and Rockets - Heartbreak Soup",
        "Cerebus - High Society",
        "Elfquest - The Grand Quest",
        "Groo the Wanderer - Cheese Dip",
        "Nexus - Capital City",
        "American Flagg - Hard Times",
        "Mage - The Hero Defined",
        "Grendel - Devil by the Deed",
        "Scout - War Shaman",
        "Badger - Hexbreaker",
        "Grimjack - Killer Instinct",
    ]

    dismissed_names = [
        # These look like they were intentionally skipped
        "2000 AD Annual 1985",
        "Wizard Magazine Specials",
        "Marvel Swimsuit Special",
        "DC Holiday Special 2023",
        "Free Comic Book Day 2024 Sampler",
        "Comic Shop News Digest",
        "Previews Catalog May 2024",
        "Diamond Distributors Exclusive",
        "Overstreet Price Guide 2024",
        "Wizard Top 10 Lists",
        "Marvel Handbook A-Z Update",
        "DC Who's Who Supplemental",
        "Comics Buyer's Guide Annual",
        "Image Firsts Reprint Bundle",
        "Dark Horse Presents Anthology v3",
        "Fantagraphics Preview Catalog",
        "IDW Deviations One-Shots",
        "Archie Digest Library Collection",
        "Harvey Comics Classics Reprint",
        "Gold Key Spotlight Archive",
        "Charlton Bullseye Collection",
        "Atlas Comics Revival",
        "Crossgen Chronicles",
        "Malibu Universe Handbook",
        "Valiant Era Handbook 2024",
    ]

    count = 0
    publishers = [
        "DC Comics",
        "Marvel",
        "Image Comics",
        "Dark Horse",
        "IDW Publishing",
        "Boom! Studios",
        "Valiant",
        "Dynamite",
        "Aftershock",
        "Oni Press",
    ]
    years = list(range(1985, 2025))

    # Orphaned (NO_MATCH) — 45 records
    for i, name in enumerate(orphan_names):
        job = completed_jobs[i % len(completed_jobs)]
        year = years[i % len(years)]
        series = ImportedSeries(
            import_job_id=job.id,
            status=ImportSeriesStatus.NO_MATCH,
            raw_series_name=name,
            raw_year=year,
            raw_publisher=publishers[i % len(publishers)],
            file_count=(i % 30) + 3,
            source_folder=f"/mnt/nas/comics/{name.replace(' ', '_').replace('-', '').lower()}",
            sample_paths=[f"{name} #{str(n).zfill(3)}.cbz" for n in range(1, min(4, (i % 5) + 2))],
            has_files=True,
        )
        session.add(series)
        count += 1

    # Dismissed (SKIPPED) — 25 records
    for i, name in enumerate(dismissed_names):
        job = completed_jobs[i % len(completed_jobs)]
        year = years[(i + 20) % len(years)]
        series = ImportedSeries(
            import_job_id=job.id,
            status=ImportSeriesStatus.SKIPPED,
            raw_series_name=name,
            raw_year=year,
            raw_publisher=publishers[(i + 3) % len(publishers)],
            file_count=(i % 10) + 1,
            source_folder=f"/mnt/nas/comics/misc/{name.replace(' ', '_').lower()}",
            sample_paths=[f"{name}.cbz"],
            has_files=True,
        )
        session.add(series)
        count += 1

    await session.flush()
    print(
        f"  Created {count} orphaned/dismissed series "
        f"({len(orphan_names)} orphaned, {len(dismissed_names)} dismissed)"
    )
    return count


async def main() -> None:
    """Seed import history + orphaned series data."""
    settings = get_settings()
    engine = create_async_engine(settings.db_url)

    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        print("=" * 60)
        print("  Pullbox — Import History + Orphaned Series Seed")
        print("=" * 60)
        print()

        jobs = await _seed_import_jobs(session)
        orphans = await _seed_orphaned_series(session)

        await session.commit()

        print()
        if jobs + orphans == 0:
            print("Data already seeded, nothing new created.")
        else:
            print(f"Done: {jobs} import jobs, {orphans} orphaned/dismissed series")
            print()
            print("Pages to test:")
            print("  /import/history        — 65 jobs (50/page = 2 pages)")
            print("  /import/orphaned       — 45 unmatched (25/page = 2 pages)")
            print("  /import/orphaned?tab=dismissed — 25 dismissed (25/page = 1 page)")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
