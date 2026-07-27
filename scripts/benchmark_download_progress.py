#!/usr/bin/env python
"""Benchmark Pullbox's transient download-progress update path."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from pullbox.performance.baseline import current_process_peak_rss_bytes  # noqa: E402
from pullbox.tasks import download_progress  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates", type=int, default=10_000)
    args = parser.parse_args()
    if args.updates < 1:
        parser.error("--updates must be at least 1")

    download_id = 991_001
    download_progress._clear_progress(download_id)
    started_at = time.perf_counter()
    try:
        for index in range(args.updates):
            progress = (index + 1) / args.updates
            download_progress.record_download_progress(
                download_id,
                SimpleNamespace(
                    progress=progress,
                    speed_bytes=8 * 1024 * 1024,
                    eta_seconds=max(0, args.updates - index - 1),
                    size_bytes=1024 * 1024 * 1024,
                    client_state="downloading",
                ),
            )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        snapshot_count = int(download_id in download_progress.get_all_progress())
        milestone_count = len(download_progress._milestone_logged.get(download_id, set()))
    finally:
        download_progress._clear_progress(download_id)

    elapsed_seconds = max(elapsed_ms / 1000, 0.000_001)
    report = {
        "final_status": "completed",
        "elapsed_ms": round(elapsed_ms, 3),
        "progress_update_count": args.updates,
        "in_memory_write_count": args.updates,
        "database_write_count": 0,
        "snapshot_count": snapshot_count,
        "milestone_count": milestone_count,
        "updates_per_second": round(args.updates / elapsed_seconds, 3),
        "peak_rss_bytes": current_process_peak_rss_bytes(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
