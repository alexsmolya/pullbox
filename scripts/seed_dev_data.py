"""Seed script for populating the database with sample data for development.

Idempotent: safe to run multiple times. Existing records are skipped.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_dev_data.py
"""

import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the project root is on sys.path so pullbox is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.models.base import Base
from pullbox.models.client import DownloadClientConfig
from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig
from pullbox.models.download import DownloadClientType
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import LibraryRoot
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series, SeriesStatus
from pullbox.models.user import User


async def _seed_publishers(session: AsyncSession) -> dict[str, Publisher]:
    """Seed publisher records. Returns name->Publisher mapping."""
    data = [
        {"name": "DC Comics", "comicvine_id": 10},
        {"name": "Marvel", "comicvine_id": 31},
        {"name": "Image Comics", "comicvine_id": 1868},
    ]
    publishers: dict[str, Publisher] = {}
    count = 0
    for item in data:
        existing = (
            await session.execute(select(Publisher).where(Publisher.name == item["name"]))
        ).scalar_one_or_none()
        if existing:
            publishers[item["name"]] = existing
            print(f"  Publisher '{item['name']}' already exists, skipping.")
        else:
            pub = Publisher(**item)
            session.add(pub)
            await session.flush()
            publishers[item["name"]] = pub
            count += 1
            print(f"  Created publisher: {item['name']}")
    return publishers


async def _seed_series(
    session: AsyncSession, publishers: dict[str, Publisher]
) -> dict[str, Series]:
    """Seed series records. Returns title->Series mapping."""
    data = [
        {
            "title": "Batman",
            "sort_title": "Batman",
            "year_start": 2016,
            "year_end": 2024,
            "status": SeriesStatus.ENDED,
            "comicvine_id": 97508,
            "issue_count": 150,
            "monitored": True,
            "publisher": "DC Comics",
        },
        {
            "title": "The Amazing Spider-Man",
            "sort_title": "Amazing Spider-Man, The",
            "year_start": 2022,
            "status": SeriesStatus.CONTINUING,
            "comicvine_id": 145830,
            "issue_count": 60,
            "monitored": True,
            "publisher": "Marvel",
        },
        {
            "title": "Saga",
            "sort_title": "Saga",
            "year_start": 2012,
            "status": SeriesStatus.CONTINUING,
            "comicvine_id": 43729,
            "issue_count": 66,
            "monitored": True,
            "publisher": "Image Comics",
        },
        {
            "title": "Superman",
            "sort_title": "Superman",
            "year_start": 2023,
            "status": SeriesStatus.CONTINUING,
            "comicvine_id": 155100,
            "issue_count": 20,
            "monitored": False,
            "publisher": "DC Comics",
        },
        {
            "title": "X-Men",
            "sort_title": "X-Men",
            "year_start": 2021,
            "year_end": 2024,
            "status": SeriesStatus.ENDED,
            "comicvine_id": 140234,
            "issue_count": 35,
            "monitored": True,
            "publisher": "Marvel",
        },
    ]
    all_series: dict[str, Series] = {}
    count = 0
    for item in data:
        pub_name = item.pop("publisher")
        existing = (
            await session.execute(select(Series).where(Series.comicvine_id == item["comicvine_id"]))
        ).scalar_one_or_none()
        if existing:
            all_series[item["title"]] = existing
            print(f"  Series '{item['title']}' already exists, skipping.")
        else:
            s = Series(**item, publisher_id=publishers[pub_name].id)
            session.add(s)
            await session.flush()
            all_series[item["title"]] = s
            count += 1
            year = item.get("year_start", "?")
            print(f"  Created series: {item['title']} ({year})")
    return all_series


async def _seed_issues(session: AsyncSession, all_series: dict[str, Series]) -> int:
    """Seed issue records. Returns count created."""
    data = [
        ("Batman", 1.0, "I Am Gotham Part One", date(2016, 6, 15), IssueStatus.OWNED),
        ("Batman", 2.0, "I Am Gotham Part Two", date(2016, 7, 6), IssueStatus.OWNED),
        ("Batman", 3.0, "I Am Gotham Part Three", date(2016, 7, 20), IssueStatus.WANTED),
        ("Batman", 50.0, "The Wedding", date(2018, 7, 4), IssueStatus.OWNED),
        ("The Amazing Spider-Man", 1.0, "The New Beginning", date(2022, 4, 6), IssueStatus.OWNED),
        ("The Amazing Spider-Man", 2.0, None, date(2022, 5, 4), IssueStatus.OWNED),
        ("The Amazing Spider-Man", 3.0, None, date(2022, 6, 1), IssueStatus.WANTED),
        (
            "The Amazing Spider-Man",
            25.0,
            "Anniversary Issue",
            date(2023, 3, 8),
            IssueStatus.DOWNLOADING,
        ),
        ("Saga", 1.0, None, date(2012, 3, 14), IssueStatus.OWNED),
        ("Saga", 2.0, None, date(2012, 4, 11), IssueStatus.OWNED),
        ("Saga", 55.0, None, date(2022, 1, 26), IssueStatus.WANTED),
        ("Superman", 1.0, "Supercorp Part One", date(2023, 2, 21), IssueStatus.SKIPPED),
        ("Superman", 2.0, None, date(2023, 3, 21), IssueStatus.SKIPPED),
        ("X-Men", 1.0, "Fearless", date(2021, 7, 7), IssueStatus.OWNED),
        ("X-Men", 10.0, None, date(2022, 3, 16), IssueStatus.WANTED),
        ("X-Men", 35.0, "Finale", date(2024, 6, 5), IssueStatus.SKIPPED),
    ]
    count = 0
    for series_title, issue_num, title, rel_date, status in data:
        series = all_series[series_title]
        existing = (
            await session.execute(
                select(Issue).where(
                    Issue.series_id == series.id,
                    Issue.issue_number == issue_num,
                )
            )
        ).scalar_one_or_none()
        if existing:
            print(f"  Issue '{series_title}' #{issue_num} already exists, skipping.")
        else:
            issue = Issue(
                series_id=series.id,
                issue_number=issue_num,
                title=title,
                release_date=rel_date,
                status=status,
            )
            session.add(issue)
            count += 1
            print(f"  Created issue: {series_title} #{issue_num}")
    return count


async def _seed_system_config(session: AsyncSession) -> int:
    """Seed SystemConfig defaults. Returns count created."""
    count = 0
    for key, (value, value_type) in DEFAULT_SYSTEM_CONFIG.items():
        existing = await session.get(SystemConfig, key)
        if existing:
            print(f"  SystemConfig '{key}' already exists, skipping.")
        else:
            session.add(SystemConfig(key=key, value=value, value_type=value_type))
            count += 1
            print(f"  Created SystemConfig: {key} = {value}")
    return count


async def seed(session: AsyncSession) -> None:
    """Insert all seed data, skipping anything that already exists."""
    publishers = await _seed_publishers(session)
    all_series = await _seed_series(session, publishers)
    issues_count = await _seed_issues(session, all_series)

    # --- Library Root ---
    roots_count = 0
    existing_root = (
        await session.execute(select(LibraryRoot).where(LibraryRoot.path == "/comics"))
    ).scalar_one_or_none()
    if existing_root:
        print("  Library root '/comics' already exists, skipping.")
    else:
        session.add(LibraryRoot(name="Comics Library", path="/comics"))
        roots_count = 1
        print("  Created library root: /comics")

    # --- Indexer Config (disabled placeholder) ---
    indexers_count = 0
    existing_indexer = (
        await session.execute(select(IndexerConfig).where(IndexerConfig.name == "NZBgeek (sample)"))
    ).scalar_one_or_none()
    if existing_indexer:
        print("  Indexer 'NZBgeek (sample)' already exists, skipping.")
    else:
        session.add(
            IndexerConfig(
                name="NZBgeek (sample)",
                indexer_type=IndexerType.NEWZNAB,
                url="https://api.nzbgeek.info",
                api_key="placeholder-api-key",
                enabled=False,
                priority=50,
            )
        )
        indexers_count = 1
        print("  Created indexer: NZBgeek (sample) [disabled]")

    # --- Download Client Config (disabled placeholder) ---
    clients_count = 0
    existing_client = (
        await session.execute(
            select(DownloadClientConfig).where(DownloadClientConfig.name == "SABnzbd (sample)")
        )
    ).scalar_one_or_none()
    if existing_client:
        print("  Client 'SABnzbd (sample)' already exists, skipping.")
    else:
        session.add(
            DownloadClientConfig(
                name="SABnzbd (sample)",
                client_type=DownloadClientType.SABNZBD,
                url="http://localhost:8080",
                api_key="placeholder-api-key",
                enabled=False,
                priority=50,
                category="comics",
            )
        )
        clients_count = 1
        print("  Created download client: SABnzbd (sample) [disabled]")

    # --- Admin User ---
    users_count = 0
    existing_user = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one_or_none()
    if existing_user:
        print("  User 'admin' already exists, skipping.")
    else:
        session.add(
            User(
                username="admin",
                password_hash=bcrypt.hashpw(b"pullbox", bcrypt.gensalt()).decode(),
                is_active=True,
                last_login_at=datetime.now(UTC),
            )
        )
        users_count = 1
        print("  Created user: admin (password: pullbox)")

    # --- SystemConfig Defaults ---
    config_count = await _seed_system_config(session)
    if config_count:
        print(f"  Seeded {config_count} SystemConfig defaults")

    await session.commit()

    # --- Summary ---
    total = issues_count + roots_count + indexers_count + clients_count + users_count + config_count
    print()
    if total == 0:
        print("Data already exists, skipping.")
    else:
        print(
            f"Seed complete: created {issues_count} issues, "
            f"{roots_count} library roots, {indexers_count} indexers, "
            f"{clients_count} download clients, {users_count} users, "
            f"{config_count} system config entries."
        )


async def main() -> None:
    """Create tables (if needed) and seed data."""
    settings = get_settings()

    # Ensure the database directory exists for SQLite file paths.
    db_url = settings.db_url
    if "sqlite" in db_url:
        db_path = db_url.split("///", 1)[-1] if "///" in db_url else None
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(db_url)

    # Ensure all tables exist.
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        print("Seeding development data...")
        print()
        await seed(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
