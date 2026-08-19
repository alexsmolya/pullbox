#!/usr/bin/env python
"""Benchmark the existing local library copy path with a synthetic file."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from pullbox.core.library_transfer import transfer_into_library  # noqa: E402
from pullbox.performance.baseline import current_process_peak_rss_bytes  # noqa: E402

_MIB = 1024 * 1024


def _write_fixture(path: Path, size_bytes: int) -> None:
    chunk = b"pullbox-direct-download-baseline\n" * 32_768
    remaining = size_bytes
    with path.open("wb") as handle:
        while remaining:
            block = chunk[: min(len(chunk), remaining)]
            handle.write(block)
            remaining -= len(block)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mib", type=int, default=64)
    args = parser.parse_args()
    if args.size_mib < 1:
        parser.error("--size-mib must be at least 1")

    size_bytes = args.size_mib * _MIB
    progress: list[int] = []
    with tempfile.TemporaryDirectory(prefix="pullbox-transfer-benchmark-") as temp:
        root = Path(temp)
        source = root / "source.cbz"
        destination = root / "destination.cbz"
        _write_fixture(source, size_bytes)

        started_at = time.perf_counter()
        transfer_into_library(
            source,
            destination,
            "copy",
            lambda transferred, _total: progress.append(transferred),
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        bytes_transferred = destination.stat().st_size

    elapsed_seconds = max(elapsed_ms / 1000, 0.000_001)
    report = {
        "final_status": "completed",
        "elapsed_ms": round(elapsed_ms, 3),
        "fixture_size_mib": args.size_mib,
        "bytes_transferred": bytes_transferred,
        "throughput_mib_per_second": round((bytes_transferred / _MIB) / elapsed_seconds, 3),
        "progress_callback_count": len(progress),
        "progress_monotonic": progress == sorted(progress),
        "progress_completed": bool(progress and progress[-1] == bytes_transferred),
        "cancel_supported": False,
        "idle_detection_supported": False,
        "peak_rss_bytes": current_process_peak_rss_bytes(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
