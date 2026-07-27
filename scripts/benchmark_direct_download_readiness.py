#!/usr/bin/env python
"""Capture the offline DD-0 performance and request-count baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from pullbox.performance.baseline import write_report  # noqa: E402
from pullbox.performance.direct_download_baseline import (  # noqa: E402
    build_readiness_report,
    default_workloads,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("quick", "standard"), default="standard")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_readiness_report(
        repo_root=REPO_ROOT,
        workloads=default_workloads(profile=args.profile),
        samples=args.samples,
        timeout_seconds=args.timeout,
    )
    report["settings"]["profile"] = args.profile  # type: ignore[index]
    if args.output is not None:
        write_report(report, args.output)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
