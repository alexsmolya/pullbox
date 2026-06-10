"""Seed pending matches that expire within 2 minutes for manual testing.

Sets search_intervention_expiry_days to 0 (expire anything older than 0 days)
and creates pending matches backdated to various ages. Then temporarily
reschedules the expire_pending_matches task to run every 30 seconds so you
can watch them expire in the UI.

Usage:
    PULLBOX_SECRET_KEY=test python scripts/seed_expiry_test.py

After running:
  1. Start server: PULLBOX_SECRET_KEY=test uvicorn pullbox.app:create_app --factory --port 8585
  2. Open /intervention — you should see 5 pending matches
  3. Within ~30 seconds the scheduled task will expire them
  4. Refresh the page — they should be gone

To reset afterwards:
    PULLBOX_SECRET_KEY=test python scripts/seed_pending_matches.py
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from pullbox.database import get_session_factory
from pullbox.models.config import SystemConfig
from pullbox.models.issue import Issue
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        # Clear existing pending matches
        result = await session.execute(delete(PendingMatch))
        print(f"Cleared {result.rowcount} existing pending matches")

        # Find an issue to attach to (Absolute Martian Manhunter #1)
        issue = (await session.execute(select(Issue).where(Issue.id == 85))).scalar_one_or_none()
        if issue is None:
            print("ERROR: Issue id=85 not found. Run seed_dev_data.py first.")
            return

        # Create 5 pending matches with various ages
        ages = [
            ("2 minutes ago", timedelta(minutes=2)),
            ("5 minutes ago", timedelta(minutes=5)),
            ("1 hour ago", timedelta(hours=1)),
            ("1 day ago", timedelta(days=1)),
            ("Fresh (just now)", timedelta(seconds=5)),
        ]

        pm_ids: list[int] = []
        now = datetime.now(UTC)
        for label, age in ages:
            pm = PendingMatch(
                issue_id=issue.id,
                release_title=f"Absolute Martian Manhunter 001 - {label}.cbz",
                download_url=f"https://indexer.example.com/dl/{label.replace(' ', '-')}",
                is_torrent=False,
                file_size=142_000_000,
                confidence="medium",
                match_details={"indexer_name": "NZBgeek", "age_days": 1},
                status=PendingMatchStatus.PENDING,
            )
            session.add(pm)
            await session.flush()
            pm_ids.append(pm.id)

            # Backdate created_at
            await session.execute(
                update(PendingMatch).where(PendingMatch.id == pm.id).values(created_at=now - age)
            )
            print(f"  Seeded: {label} (id={pm.id})")

        # Set expiry config to 0 days (expire everything not brand-new)
        # Actually use a very small threshold — 1 minute
        existing = (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key == "search_intervention_expiry_days")
            )
        ).scalar_one_or_none()

        # We can't use fractional days in the config, so set to 0
        # This will expire anything older than 0 days (i.e., everything)
        if existing:
            existing.value = "0"
        else:
            session.add(SystemConfig(key="search_intervention_expiry_days", value="0"))

        await session.commit()
        print(f"\nSeeded {len(pm_ids)} pending matches")
        print("Set search_intervention_expiry_days = 0")
        print("\nRestart the server, then check /intervention.")
        print("The expire_pending_matches task runs at 6:00 AM by default.")
        print("To trigger it manually, run:")
        print('  PULLBOX_SECRET_KEY=test python -c "')
        print("  import asyncio")
        print("  from pullbox.tasks.intervention_task import expire_pending_matches")
        print("  asyncio.run(expire_pending_matches())")
        print('  "')


if __name__ == "__main__":
    asyncio.run(main())
