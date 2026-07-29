"""Indexer fan-out, category filtering, and health tracking for searches."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from pullbox.core.log_deduper import log_deduped_warning
from pullbox.providers.base import ReleaseResult, SearchQuery
from pullbox.services.search_query_helpers import (
    DEFAULT_COMIC_CATEGORIES,
    _is_comic_category,
)

if TYPE_CHECKING:
    from pullbox.models.indexer import IndexerConfig
    from pullbox.providers.base import Indexer, ProviderRegistry


logger = structlog.get_logger(__name__)

DEFAULT_INDEXER_FAILURE_THRESHOLD = 3
INDEXER_BACKOFF_SECONDS = [900, 3600, 7200]  # 15min, 1hr, 2hr maximum

SearchSingleIndexerFunc = Callable[
    ["Indexer", SearchQuery, "IndexerConfig | None", int],
    Awaitable["IndexerSearchAttempt"],
]


@dataclass(frozen=True)
class IndexerSearchAttempt:
    """Results and health status for one isolated indexer request."""

    results: list[ReleaseResult]
    status: str = "completed"
    error: str | None = None


def calculate_backoff(
    failure_count: int,
    threshold: int = DEFAULT_INDEXER_FAILURE_THRESHOLD,
) -> int:
    """Return backoff seconds for the given failure count."""
    index = min(failure_count - threshold, len(INDEXER_BACKOFF_SECONDS) - 1)
    return INDEXER_BACKOFF_SECONDS[max(0, index)]


async def search_indexers(
    registry: ProviderRegistry,
    query: SearchQuery,
    *,
    indexer_configs: dict[int, IndexerConfig] | None = None,
    failure_threshold: int = DEFAULT_INDEXER_FAILURE_THRESHOLD,
    search_single_indexer_func: SearchSingleIndexerFunc | None = None,
    log: structlog.stdlib.BoundLogger | None = None,
    timing_collector: list[dict[str, object]] | None = None,
    ignore_backoff: bool = False,
) -> list[ReleaseResult]:
    """Search all registered indexers concurrently and aggregate results."""
    active_logger = log or logger
    search_single = search_single_indexer_func or search_single_indexer

    indexer_items = registry.get_indexer_items()
    if inspect.isawaitable(indexer_items):
        indexer_items = await indexer_items
    if not indexer_items:
        log_deduped_warning(
            active_logger,
            "search_no_indexers",
            key="search_no_indexers",
            action_required="Enable at least one indexer to perform searches.",
        )
        return []

    now = datetime.now(UTC)
    search_tasks: list[tuple[int, Indexer, SearchQuery, IndexerConfig | None]] = []
    for config_id, indexer in indexer_items:
        cfg = indexer_configs.get(config_id) if indexer_configs else None

        if not ignore_backoff and cfg and cfg.disabled_until and cfg.disabled_until > now:
            active_logger.debug(
                "search_indexer_skipped",
                indexer=indexer.name,
                disabled_until=str(cfg.disabled_until),
            )
            if timing_collector is not None:
                timing_collector.append(
                    {
                        "query": query.series_title,
                        "indexer": indexer.name,
                        "status": "skipped",
                        "elapsed_ms": 0,
                        "raw_count": 0,
                        "result_count": 0,
                        "filtered_count": 0,
                        "categories": query.categories,
                    }
                )
            continue

        indexer_query = query
        if cfg and str(cfg.indexer_type) == "newznab" and not query.categories:
            indexer_query = SearchQuery(
                series_title=query.series_title,
                issue_number=query.issue_number,
                year=query.year,
                issue_type=query.issue_type,
                categories=DEFAULT_COMIC_CATEGORIES,
            )

        search_tasks.append((config_id, indexer, indexer_query, cfg))

    if not search_tasks:
        return []

    async def _timed_search(
        config_id: int,
        indexer: Indexer,
        indexer_query: SearchQuery,
        cfg: IndexerConfig | None,
    ) -> tuple[int, Indexer, SearchQuery, IndexerSearchAttempt, int]:
        started_at = time.monotonic()
        attempt = await search_single(indexer, indexer_query, cfg, failure_threshold)
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return config_id, indexer, indexer_query, attempt, elapsed_ms

    raw_results = await asyncio.gather(
        *[
            _timed_search(config_id, indexer, indexer_query, cfg)
            for config_id, indexer, indexer_query, cfg in search_tasks
        ],
    )

    all_results: list[ReleaseResult] = []
    for config_id, indexer, indexer_query, attempt, elapsed_ms in raw_results:
        results = attempt.results
        if results:
            active_logger.debug(
                "search_indexer_raw_results",
                indexer=indexer.name,
                query=indexer_query.series_title,
                categories=indexer_query.categories,
                count=len(results),
                sample_titles=[result.title for result in results[:5]],
                sample_categories=[result.category for result in results[:5]],
            )

        before = len(results)
        result_indexer_id = config_id if config_id >= 0 else None
        filtered_results = [
            replace(result, indexer_id=result_indexer_id)
            for result in results
            if _is_comic_category(result.category)
        ]
        filtered = before - len(filtered_results)
        if timing_collector is not None:
            timing: dict[str, object] = {
                "query": indexer_query.series_title,
                "indexer": indexer.name,
                "status": attempt.status,
                "elapsed_ms": elapsed_ms,
                "raw_count": before,
                "result_count": len(filtered_results),
                "filtered_count": filtered,
                "categories": indexer_query.categories,
            }
            if attempt.error is not None:
                timing["error"] = attempt.error
            timing_collector.append(timing)
        if filtered:
            active_logger.debug(
                "search_category_filtered",
                indexer=indexer.name,
                filtered=filtered,
                remaining=len(filtered_results),
            )

        all_results.extend(filtered_results)

    return all_results


async def search_single_indexer(
    indexer: Indexer,
    query: SearchQuery,
    cfg: IndexerConfig | None = None,
    failure_threshold: int = DEFAULT_INDEXER_FAILURE_THRESHOLD,
    failure_cohort: set[int] | None = None,
) -> IndexerSearchAttempt:
    """Search a single indexer, handling errors and health tracking."""
    log = logger.bind(indexer=indexer.name, query=query.series_title)
    log.debug(
        "search_indexer_query",
        issue_number=query.issue_number,
        year=query.year,
        issue_type=str(query.issue_type) if query.issue_type else None,
        categories=query.categories,
    )
    started_at = time.monotonic()
    try:
        results = await indexer.search(query)
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        log.debug("search_indexer_results", count=len(results), elapsed_ms=elapsed_ms)

        if cfg is not None:
            cfg.failure_count = 0
            cfg.disabled_until = None
            cfg.last_success_at = datetime.now(UTC)
            cfg.last_error = None
            if failure_cohort is not None:
                failure_cohort.discard(_config_health_key(cfg))

        return IndexerSearchAttempt(results=results)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        log.warning("search_indexer_error", elapsed_ms=elapsed_ms, error=str(exc))

        if cfg is not None:
            health_key = _config_health_key(cfg)
            record_failure = failure_cohort is None or health_key not in failure_cohort
            if record_failure:
                cfg.failure_count += 1
                if failure_cohort is not None:
                    failure_cohort.add(health_key)
            cfg.last_failure_at = datetime.now(UTC)
            cfg.last_error = f"Search failed for query: {query.series_title}"

            if record_failure and cfg.failure_count >= failure_threshold:
                backoff = calculate_backoff(cfg.failure_count, failure_threshold)
                cfg.disabled_until = datetime.now(UTC) + timedelta(seconds=backoff)
                log.warning(
                    "search_indexer_disabled",
                    failure_count=cfg.failure_count,
                    disabled_until=str(cfg.disabled_until),
                    backoff_seconds=backoff,
                )

        return IndexerSearchAttempt(results=[], status="failed", error=str(exc))


def _config_health_key(config: IndexerConfig) -> int:
    """Return a stable key for deduplicating failures within one search run."""

    config_id = getattr(config, "id", None)
    return int(config_id) if config_id is not None else id(config)
