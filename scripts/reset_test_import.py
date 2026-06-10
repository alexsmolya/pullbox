#!/usr/bin/env python3
"""Reset test import — restore files to original locations and clean up DB.

Reads the import_files table to find original file paths, moves files back
from the library, deletes import-created series/issues/library_files from
the DB, and removes empty series folders from the comics directory.

Usage:
    PULLBOX_SECRET_KEY=test PULLBOX_DB_URL="sqlite+aiosqlite:////data/pullbox.db" \
        python scripts/reset_test_import.py

Set DRY_RUN=1 to preview without making changes:
    DRY_RUN=1 PULLBOX_SECRET_KEY=test PULLBOX_DB_URL="sqlite+aiosqlite:////data/pullbox.db" \
        python scripts/reset_test_import.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
DB_URL = os.environ.get("PULLBOX_DB_URL", "sqlite+aiosqlite:////data/pullbox.db")


async def reset() -> None:
    engine = create_async_engine(DB_URL)

    async with engine.begin() as conn:
        # ── 1. Move files back to original locations ──────────────────
        print("\n=== Step 1: Restore files to original locations ===")
        rows = await conn.execute(
            text(
                "SELECT if2.file_path, lf.file_path "
                "FROM import_files if2 "
                "JOIN library_files lf ON if2.library_file_id = lf.id "
                "WHERE if2.library_file_id IS NOT NULL"
            )
        )
        file_moves = rows.all()

        for orig_path, lib_path in file_moves:
            orig = Path(orig_path)
            lib = Path(lib_path)
            if lib.exists():
                # Ensure original parent directory exists
                orig.parent.mkdir(parents=True, exist_ok=True)
                print(f"  MOVE {lib} -> {orig}")
                if not DRY_RUN:
                    shutil.move(str(lib), str(orig))
            elif orig.exists():
                print(f"  SKIP {orig.name} (already at original location)")
            else:
                print(f"  WARN {lib} not found, {orig} not found — file may be lost")

        print(f"  {len(file_moves)} file(s) to restore")

        # ── 2. Get series IDs created by imports ──────────────────────
        print("\n=== Step 2: Identify import-created series ===")
        series_rows = await conn.execute(
            text("SELECT DISTINCT series_id FROM import_series WHERE series_id IS NOT NULL")
        )
        series_ids = [r[0] for r in series_rows.all()]
        print(f"  Found {len(series_ids)} series to delete: {series_ids}")

        # Get series folder paths before deleting
        if series_ids:
            placeholders = ",".join(str(s) for s in series_ids)
            path_rows = await conn.execute(
                text(f"SELECT id, path, title FROM series WHERE id IN ({placeholders})")
            )
            series_paths = [(r[0], r[1], r[2]) for r in path_rows.all()]
        else:
            series_paths = []

        # ── 3. Delete DB records ──────────────────────────────────────
        print("\n=== Step 3: Clean up database ===")

        # Delete library_files created by import
        lf_rows = await conn.execute(
            text(
                "SELECT DISTINCT library_file_id FROM import_files "
                "WHERE library_file_id IS NOT NULL"
            )
        )
        lf_ids = [r[0] for r in lf_rows.all()]

        if lf_ids:
            lf_placeholders = ",".join(str(i) for i in lf_ids)
            if DRY_RUN:
                print(f"  library_files: {len(lf_ids)} would be deleted")
            else:
                result = await conn.execute(
                    text(f"DELETE FROM library_files WHERE id IN ({lf_placeholders})")
                )
                print(f"  library_files: {result.rowcount} deleted")

        # Delete import tables
        for table in ["import_files", "import_job_logs", "import_series", "import_jobs"]:
            if DRY_RUN:
                count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
                print(f"  {table}: {count} would be deleted")
            else:
                result = await conn.execute(text(f"DELETE FROM {table}"))
                print(f"  {table}: {result.rowcount} deleted")

        # Delete issues for import-created series
        if series_ids:
            placeholders = ",".join(str(s) for s in series_ids)
            if DRY_RUN:
                count = (
                    await conn.execute(
                        text(f"SELECT COUNT(*) FROM issues WHERE series_id IN ({placeholders})")
                    )
                ).scalar_one()
                print(f"  issues: {count} would be deleted")
            else:
                result = await conn.execute(
                    text(f"DELETE FROM issues WHERE series_id IN ({placeholders})")
                )
                print(f"  issues: {result.rowcount} deleted")

            # Delete the series themselves
            if DRY_RUN:
                print(f"  series: {len(series_ids)} would be deleted")
            else:
                result = await conn.execute(
                    text(f"DELETE FROM series WHERE id IN ({placeholders})")
                )
                print(f"  series: {result.rowcount} deleted")

        # ── 4. Remove empty series folders from comics directory ──────
        print("\n=== Step 4: Remove series folders from library ===")
        for _series_id, series_path, _title in series_paths:
            if series_path:
                folder = Path(series_path)
                if folder.exists():
                    # Check if folder is empty (or only has non-comic files like cover.jpg)
                    remaining = list(folder.iterdir())
                    print(f"  DELETE {folder} ({len(remaining)} remaining items)")
                    if not DRY_RUN:
                        shutil.rmtree(folder)
                else:
                    print(f"  SKIP {folder} (already gone)")

    await engine.dispose()

    mode = "DRY RUN" if DRY_RUN else "COMPLETE"
    print(f"\n=== Reset {mode} ===")
    if DRY_RUN:
        print("  Re-run without DRY_RUN=1 to apply changes.")


if __name__ == "__main__":
    asyncio.run(reset())
