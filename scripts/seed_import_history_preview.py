#!/usr/bin/env python3
"""Seed repeatable preview rows for the Import History table.

Creates a small set of import jobs under a dedicated source-path namespace so
the History tab shows every action-icon combination:

- paused: log, resume, delete
- completed: log, view results, rollback
- failed: log, view results, rollback, delete
- cancelled: log, retry, delete
- rolled back: log, retry, delete

The script is idempotent. It deletes any existing preview rows whose
``source_path`` starts with ``/preview/import-history/`` and recreates them.

Usage:
    python scripts/seed_import_history_preview.py
    python scripts/seed_import_history_preview.py --clear-only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pullbox.config import get_settings
from pullbox.models.import_job import (
    ImportJob,
    ImportJobLog,
    ImportJobStatus,
    ImportSourceType,
)

_PREVIEW_PREFIX = "/preview/import-history/"


def _preview_definitions() -> list[dict[str, object]]:
    now = datetime.now(UTC)
    return [
        {
            "slug": "paused",
            "status": ImportJobStatus.PAUSED,
            "created_at": now - timedelta(minutes=5),
            "progress_snapshot": {
                "mode": "import",
                "phase": "importing",
                "progress": 64,
                "status": ImportJobStatus.PAUSED.value,
                "message": "Import paused while converting preview-01.cbz.",
            },
            "counts": {
                "series_found": 12,
                "series_imported": 4,
                "series_failed": 0,
                "series_no_match": 1,
            },
            "logs": [
                ("info", "import_paused", "Preview job paused on request."),
                ("info", "import_checkpoint", "Paused during file conversion stage."),
            ],
            "import_started_at": now - timedelta(minutes=12),
            "import_completed_at": None,
        },
        {
            "slug": "completed",
            "status": ImportJobStatus.COMPLETED,
            "created_at": now - timedelta(minutes=15),
            "progress_snapshot": {
                "mode": "import",
                "phase": "done",
                "progress": 100,
                "status": ImportJobStatus.COMPLETED.value,
                "message": "Import finished successfully.",
            },
            "counts": {
                "series_found": 18,
                "series_imported": 9,
                "series_failed": 0,
                "series_no_match": 2,
            },
            "logs": [
                ("info", "import_completed", "Preview import completed successfully."),
                ("info", "import_results_ready", "Results are available for review."),
            ],
            "import_started_at": now - timedelta(minutes=24),
            "import_completed_at": now - timedelta(minutes=14),
        },
        {
            "slug": "failed",
            "status": ImportJobStatus.FAILED,
            "created_at": now - timedelta(minutes=25),
            "progress_snapshot": {
                "mode": "import",
                "phase": "done",
                "progress": 83,
                "status": ImportJobStatus.FAILED.value,
                "message": "Import failed while transferring giant-preview.pdf.",
            },
            "counts": {
                "series_found": 10,
                "series_imported": 5,
                "series_failed": 1,
                "series_no_match": 1,
            },
            "logs": [
                ("error", "import_failed", "Preview import failed during file placement."),
                ("warn", "import_partial", "Imported files remain available for rollback."),
            ],
            "import_started_at": now - timedelta(minutes=33),
            "import_completed_at": now - timedelta(minutes=23),
        },
        {
            "slug": "cancelled",
            "status": ImportJobStatus.CANCELLED,
            "created_at": now - timedelta(minutes=35),
            "progress_snapshot": {
                "mode": "rollback",
                "phase": "done",
                "progress": 100,
                "status": ImportJobStatus.CANCELLED.value,
                "message": "Import cancelled and rolled back.",
            },
            "counts": {
                "series_found": 14,
                "series_imported": 0,
                "series_failed": 0,
                "series_no_match": 3,
            },
            "logs": [
                ("info", "import_cancelled", "Preview import was cancelled by the user."),
                ("info", "import_rollback_complete", "Automatic rollback completed cleanly."),
            ],
            "import_started_at": now - timedelta(minutes=44),
            "import_completed_at": now - timedelta(minutes=34),
        },
        {
            "slug": "rolled-back",
            "status": ImportJobStatus.ROLLED_BACK,
            "created_at": now - timedelta(minutes=45),
            "progress_snapshot": {
                "mode": "rollback",
                "phase": "done",
                "progress": 100,
                "status": ImportJobStatus.ROLLED_BACK.value,
                "message": "Import rollback completed.",
            },
            "counts": {
                "series_found": 16,
                "series_imported": 0,
                "series_failed": 0,
                "series_no_match": 4,
            },
            "logs": [
                ("info", "manual_rollback_complete", "Preview rollback completed successfully."),
                ("info", "retry_ready", "Preview job is ready to retry as a new import."),
            ],
            "import_started_at": now - timedelta(minutes=56),
            "import_completed_at": now - timedelta(minutes=46),
        },
    ]


async def _clear_preview_rows(session_factory: async_sessionmaker) -> int:
    async with session_factory() as session:
        result = await session.execute(
            delete(ImportJob).where(ImportJob.source_path.like(f"{_PREVIEW_PREFIX}%"))
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _seed_preview_rows(session_factory: async_sessionmaker) -> list[int]:
    preview_rows = _preview_definitions()
    created_ids: list[int] = []

    async with session_factory() as session:
        for row in preview_rows:
            counts = row["counts"]  # type: ignore[assignment]
            job = ImportJob(
                source_path=f"{_PREVIEW_PREFIX}{row['slug']}",
                source_type=ImportSourceType.FILESYSTEM,
                status=row["status"],  # type: ignore[arg-type]
                series_found=counts["series_found"],  # type: ignore[index]
                series_imported=counts["series_imported"],  # type: ignore[index]
                series_failed=counts["series_failed"],  # type: ignore[index]
                series_no_match=counts["series_no_match"],  # type: ignore[index]
                progress_snapshot=row["progress_snapshot"],  # type: ignore[arg-type]
                import_started_at=row["import_started_at"],  # type: ignore[arg-type]
                import_completed_at=row["import_completed_at"],  # type: ignore[arg-type]
                error_message=(
                    "Preview import failed while transferring giant-preview.pdf."
                    if row["status"] == ImportJobStatus.FAILED
                    else None
                ),
            )
            job.created_at = row["created_at"]  # type: ignore[assignment]
            job.updated_at = row["created_at"]  # type: ignore[assignment]
            session.add(job)
            await session.flush()

            for offset, (level, event, message) in enumerate(row["logs"]):  # type: ignore[index]
                log = ImportJobLog(
                    import_job_id=job.id,
                    logged_at=(row["created_at"] + timedelta(seconds=offset * 12)),  # type: ignore[operator]
                    level=level,
                    event=event,
                    message=message,
                    data={"preview": True, "preview_slug": row["slug"]},
                )
                session.add(log)

            created_ids.append(job.id)

        await session.commit()
    return created_ids


async def _count_preview_rows(session_factory: async_sessionmaker) -> int:
    async with session_factory() as session:
        rows = await session.scalars(
            select(ImportJob.id).where(ImportJob.source_path.like(f"{_PREVIEW_PREFIX}%"))
        )
        return len(list(rows))


async def _main(clear_only: bool) -> None:
    engine = create_async_engine(get_settings().db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        cleared = await _clear_preview_rows(session_factory)
        print(f"Cleared {cleared} existing preview history row(s).")

        if clear_only:
            return

        created_ids = await _seed_preview_rows(session_factory)
        preview_count = await _count_preview_rows(session_factory)
        print(
            "Seeded preview import history rows:",
            ", ".join(str(job_id) for job_id in created_ids),
        )
        print(f"Preview row count is now {preview_count}.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Delete existing preview rows without recreating them.",
    )
    args = parser.parse_args()
    asyncio.run(_main(clear_only=args.clear_only))
