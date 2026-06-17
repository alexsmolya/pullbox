#!/usr/bin/env python
"""Synthetic benchmark for local issue-search processing.

This intentionally avoids real indexer/Prowlarr calls.  It measures Pullbox's
local query construction, result fan-in/dedupe, blocklist handoff, validation,
scoring, and search-details shaping around a deterministic fake result set.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from pullbox.models.issue import IssueType  # noqa: E402
from pullbox.providers.base import (  # noqa: E402
    IndexerCapabilities,
    ProviderHealthResult,
    ProviderRegistry,
    ReleaseResult,
    SearchQuery,
)
from pullbox.services.release_validator import ReleaseValidator  # noqa: E402
from pullbox.services.search_evaluation import (  # noqa: E402
    _select_best_validation,
    build_search_details,
    log_type_detection,
)
from pullbox.services.search_issue_runner import (  # noqa: E402
    search_issue_target as run_search_issue_target,
)
from pullbox.services.search_scoring import _sort_by_source_priority  # noqa: E402
from pullbox.services.search_service import SearchService  # noqa: E402
from pullbox.services.search_targets import IssueSearchTarget  # noqa: E402

logging.disable(logging.CRITICAL)
logger = structlog.get_logger("pullbox.performance.issue_search_benchmark")


class FakeIndexer:
    """Deterministic indexer returning one valid release plus noisy misses."""

    def __init__(
        self,
        *,
        name: str,
        result_count: int,
        series_title: str,
        issue_number: float,
        year: int,
        delay_ms: int,
        is_torrent: bool,
    ) -> None:
        self._name = name
        self._result_count = result_count
        self._series_title = series_title
        self._issue_number = issue_number
        self._year = year
        self._delay_ms = delay_ms
        self._is_torrent = is_torrent

    @property
    def name(self) -> str:
        return self._name

    @property
    def indexer_type(self) -> str:
        return "torznab" if self._is_torrent else "newznab"

    @property
    def supports_nzb(self) -> bool:
        return not self._is_torrent

    @property
    def supports_torrent(self) -> bool:
        return self._is_torrent

    async def search(self, query: SearchQuery) -> list[ReleaseResult]:
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)

        return [self._release(query, index) for index in range(max(self._result_count, 0))]

    async def get_capabilities(self) -> IndexerCapabilities:
        return IndexerCapabilities(categories=["7030"], search_params=["q"])

    async def test_connection(self) -> ProviderHealthResult:
        return ProviderHealthResult(True, "ok", 0)

    def _release(self, query: SearchQuery, index: int) -> ReleaseResult:
        issue = int(self._issue_number)
        if index == 0:
            title = f"{self._series_title} {issue:03d} ({self._year}) (Digital) ({self._name}).cbz"
        else:
            title = (
                f"Unrelated Benchmark Series {index:03d} "
                f"{999 - index:03d} ({self._year}) ({query.series_title}).cbz"
            )
        return ReleaseResult(
            title=title,
            indexer_name=self._name,
            download_url=f"https://benchmark.invalid/{self._name}/{query.series_title}/{index}",
            size_bytes=(80 + index) * 1024 * 1024,
            age_days=index % 30,
            seeders=50 - (index % 20) if self._is_torrent else None,
            leechers=2 if self._is_torrent else None,
            grabs=100 - index if not self._is_torrent else None,
            is_torrent=self._is_torrent,
            category="7030",
            published_at=datetime.now(UTC),
        )


async def _no_blocklist_filter(
    _session: object,
    results: list[ReleaseResult],
) -> list[ReleaseResult]:
    return list(results)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    series_title = str(args.series_title)
    issue_number = float(args.issue_number)
    year = int(args.year)
    target = IssueSearchTarget(
        issue_id=1,
        series_id=1,
        series_title=series_title,
        issue_number=issue_number,
        issue_type=IssueType.ISSUE,
        issue_title=None,
        series_year=year,
        alternate_names=[],
    )

    registry = ProviderRegistry()
    for index in range(int(args.indexer_count)):
        registry.register_indexer(
            index + 1,
            FakeIndexer(
                name=f"BenchmarkIndexer{index + 1}",
                result_count=int(args.result_count),
                series_title=series_title,
                issue_number=issue_number,
                year=year,
                delay_ms=int(args.delay_ms),
                is_torrent=index % 2 == 1,
            ),
        )

    service = SearchService(registry)
    started_at = time.monotonic()
    outcome = await run_search_issue_target(
        cast("Any", object()),
        target,
        mode=cast("Any", args.mode),
        build_issue_queries_func=service._build_issue_queries,
        build_fallback_queries_func=service._build_auto_fallback_queries,
        run_query_batch_func=service._run_query_batch,
        run_query_batch_with_provenance_func=service._run_query_batch_with_provenance,
        sort_by_source_priority_func=_sort_by_source_priority,
        filter_results_func=_no_blocklist_filter,
        validator_factory=ReleaseValidator,
        select_best_validation_func=_select_best_validation,
        build_search_details_func=build_search_details,
        log_type_detection_func=log_type_detection,
        log=logger,
    )
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    slow_indexers = outcome.search_details.get("slow_indexers")

    return {
        "final_status": "completed",
        "series_title": series_title,
        "issue_number": issue_number,
        "year": year,
        "mode": args.mode,
        "indexer_count": int(args.indexer_count),
        "result_count_per_query": int(args.result_count),
        "delay_ms_per_query": int(args.delay_ms),
        "elapsed_ms": elapsed_ms,
        "outcome_elapsed_ms": outcome.elapsed_ms,
        "query_count": outcome.query_count,
        "raw_results_count": len(outcome.raw_results),
        "filtered_results_count": len(outcome.filtered_results),
        "matched_count": len(outcome.matched),
        "rejected_count": len(outcome.rejected),
        "best_release_title": outcome.best_release.title if outcome.best_release else None,
        "search_details_rejected_count": outcome.search_details.get("rejected_count"),
        "slow_indexers_count": len(slow_indexers) if isinstance(slow_indexers, list) else 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-title", default="Benchmark Series")
    parser.add_argument("--issue-number", type=float, default=1)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--mode", choices=["fast", "deep"], default="deep")
    parser.add_argument("--indexer-count", type=int, default=2)
    parser.add_argument("--result-count", type=int, default=100)
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=0,
        help="Optional fake provider latency per query/indexer.",
    )
    return parser.parse_args()


def main() -> None:
    with contextlib.redirect_stdout(sys.stderr):
        report = asyncio.run(_run(_parse_args()))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
