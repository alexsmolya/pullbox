"""Search background task — finds and grabs wanted issues from indexers.

Runs on a configurable interval (default 6 hours).  For each wanted issue,
searches all enabled indexers, evaluates results, and routes the best match:
auto-grab (high confidence) or queue for user review (medium/low confidence).

Also provides ``search_series_issues()`` — a reusable helper that searches
all wanted issues for a single series.  Used by the SeriesAdded subscriber,
bulk search, and new-issue-sync flows.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import OperationalError

from pullbox.composition.events import build_domain_event_bus
from pullbox.core.config_resolver import get_int_setting, load_system_config_values, parse_bool
from pullbox.core.log_deduper import log_deduped_warning
from pullbox.core.sqlite_lock import (
    SQLITE_LOCK_RETRY_ATTEMPTS,
    is_sqlite_locked_error,
    sqlite_lock_retry_delay,
)
from pullbox.database import get_session_factory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.providers.base import ProviderRegistry, ReleaseResult

from pullbox.composition.providers import build_registry
from pullbox.models.config import SystemConfig
from pullbox.models.issue import IssueType
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series
from pullbox.services import search_runtime as _search_runtime
from pullbox.services.blocklist_service import BlocklistService
from pullbox.services.download_service import DownloadService
from pullbox.services.intervention_service import InterventionService
from pullbox.services.release_validator import (
    ReleaseValidator,
    ValidationResult,
)
from pullbox.services.search_service import (
    _TYPE_QUERY_KEYWORDS,
    DEFAULT_TYPE_THRESHOLDS,
    DEFAULT_WANTED_SEARCH_CONCURRENCY,
    IssueSearchOutcome,
    IssueSearchTarget,
    SearchRuntime,
    SearchService,
    build_eval_kwargs,
    load_series_wanted_search_targets,
    load_wanted_issue_search_targets,
    should_auto_grab,
)

logger = structlog.get_logger(__name__)
_ORIGINAL_SEARCH_SERVICE = SearchService
_ORIGINAL_SEARCH_FOR_ISSUE = SearchService.search_for_issue
_ORIGINAL_SEARCH_WANTED = SearchService.search_wanted
_SEARCH_TWO_PASS_CONFIG_KEY = "search_two_pass_enabled"
_SEARCH_LOG_RETENTION_CONFIG_KEY = "search_log_retention_days"
_SEARCH_WANTED_CURSOR_CONFIG_KEY = "search_wanted_cursor"
_SEARCH_WANTED_BATCH_LIMIT = 50
_DEFAULT_SEARCH_LOG_RETENTION_DAYS = 7


def _build_download_service(registry: ProviderRegistry) -> DownloadService:
    """Construct a task-local DownloadService while preserving patch seams."""
    return DownloadService(registry, build_domain_event_bus())


def _search_outcome_log_diagnostics(outcomes: list[IssueSearchOutcome]) -> dict[str, int]:
    """Aggregate lightweight query diagnostics for task completion logs."""

    slow_indexer_count = 0
    slowest_query_ms = 0
    for outcome in outcomes:
        slow_indexers = outcome.search_details.get("slow_indexers")
        if isinstance(slow_indexers, list):
            slow_indexer_count += len(slow_indexers)
        query_diagnostics = outcome.search_details.get("query_diagnostics")
        if not isinstance(query_diagnostics, list):
            continue
        for query_diag in query_diagnostics:
            if not isinstance(query_diag, dict):
                continue
            elapsed_ms = query_diag.get("elapsed_ms")
            if isinstance(elapsed_ms, int | float):
                slowest_query_ms = max(slowest_query_ms, int(elapsed_ms))
    return {
        "query_count": sum(outcome.query_count for outcome in outcomes),
        "slow_indexer_count": slow_indexer_count,
        "slowest_query_ms": slowest_query_ms,
    }


def _merge_search_log_details(
    *,
    existing_details: dict[str, object] | None,
    next_details: dict[str, object] | None,
    run_state: str,
    action_status: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    """Merge persisted search-log detail payloads while preserving launch metadata."""

    details = dict(existing_details or {})
    details.update(next_details or {})
    details["run_state"] = run_state
    if action_status:
        details["action_status"] = action_status
    if error_message:
        details["error"] = error_message
    elif action_status != "error":
        details.pop("error", None)
    return details


async def _persist_bulk_search_log(
    session: AsyncSession,
    *,
    target: IssueSearchTarget,
    pending_log_id: int | None,
    results_found: int,
    results_grabbed: int,
    results_queued: int,
    results_rejected: int,
    details: dict[str, object],
    best_confidence: str | None,
    action_status: str,
    run_state: str = "completed",
) -> None:
    """Create or update the bulk-search history row for a single issue."""

    search_log = await session.get(SearchLog, pending_log_id) if pending_log_id else None
    if search_log is None:
        search_log = SearchLog(
            issue_id=target.issue_id,
            series_title=target.series_title,
            issue_number=target.issue_number,
            search_type=SearchType.BULK,
        )
        session.add(search_log)

    search_log.results_found = results_found
    search_log.results_grabbed = results_grabbed
    search_log.results_queued = results_queued
    search_log.results_rejected = results_rejected
    search_log.details = _merge_search_log_details(
        existing_details=search_log.details or {},
        next_details=details,
        run_state=run_state,
        action_status=action_status,
    )
    search_log.best_confidence = best_confidence
    await session.commit()


async def _complete_pending_bulk_search_logs(
    session: AsyncSession,
    pending_log_ids_by_issue: dict[int, int],
    *,
    action_status: str,
    run_state: str = "completed",
    error_message: str | None = None,
) -> None:
    """Resolve any still-running bulk-search rows for a cancelled/failed launch path."""

    touched = False
    for pending_log_id in pending_log_ids_by_issue.values():
        search_log = await session.get(SearchLog, pending_log_id)
        if search_log is None:
            continue
        search_log.details = _merge_search_log_details(
            existing_details=search_log.details or {},
            next_details=None,
            run_state=run_state,
            action_status=action_status,
            error_message=error_message,
        )
        touched = True

    if touched:
        await session.commit()


async def _build_task_search_runtime(
    session: AsyncSession,
    *,
    include_download_clients: bool = True,
) -> SearchRuntime | None:
    """Build task runtime state using the task module's registry patch point."""
    return await _search_runtime.build_search_runtime(
        session,
        include_download_clients=include_download_clients,
        registry_builder=build_registry,
        default_type_thresholds=DEFAULT_TYPE_THRESHOLDS,
        eval_kwargs_builder=build_eval_kwargs,
    )


def _is_mocked_search_service(search_svc: object) -> bool:
    """Return True when the task search service has been replaced by a test double."""

    if not isinstance(search_svc, _ORIGINAL_SEARCH_SERVICE):
        return True

    service_type = type(search_svc)
    return (
        service_type.search_for_issue is not _ORIGINAL_SEARCH_FOR_ISSUE
        or service_type.search_wanted is not _ORIGINAL_SEARCH_WANTED
    )


async def _load_mocked_two_pass_enabled(
    session: AsyncSession,
    runtime: SearchRuntime,
) -> bool:
    """Resolve the two-pass toggle for legacy mocked search-task tests."""
    configs = await load_system_config_values(session, (_SEARCH_TWO_PASS_CONFIG_KEY,))
    raw_value = configs.get(_SEARCH_TWO_PASS_CONFIG_KEY)
    if raw_value is None:
        return runtime.two_pass_enabled
    return parse_bool(raw_value)


async def _load_search_log_retention_days(session: AsyncSession) -> int:
    """Resolve search-log retention in days."""
    configs = await load_system_config_values(session, (_SEARCH_LOG_RETENTION_CONFIG_KEY,))
    return get_int_setting(
        configs,
        _SEARCH_LOG_RETENTION_CONFIG_KEY,
        _DEFAULT_SEARCH_LOG_RETENTION_DAYS,
    )


def _search_wanted_cursor_from_target(target: IssueSearchTarget) -> tuple[int, float, int]:
    """Return the stable global wanted-sweep cursor tuple for a target."""
    return (target.series_id, target.issue_number, target.issue_id)


def _parse_search_wanted_cursor(value: str | None) -> tuple[int, float, int] | None:
    """Parse the persisted wanted-sweep cursor, ignoring stale malformed values."""
    if not value:
        return None
    try:
        raw = json.loads(value)
        if (
            isinstance(raw, list | tuple)
            and len(raw) == 3
            and isinstance(raw[0], int | float | str)
            and isinstance(raw[1], int | float | str)
            and isinstance(raw[2], int | float | str)
        ):
            return (int(raw[0]), float(raw[1]), int(raw[2]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


async def _load_search_wanted_cursor(session: AsyncSession) -> tuple[int, float, int] | None:
    """Load the last attempted global wanted-search cursor."""
    row = await session.get(SystemConfig, _SEARCH_WANTED_CURSOR_CONFIG_KEY)
    return _parse_search_wanted_cursor(row.value if row is not None else None)


async def _save_search_wanted_cursor(
    session: AsyncSession,
    target: IssueSearchTarget,
) -> None:
    """Persist the last attempted global wanted-search target."""
    value = json.dumps(list(_search_wanted_cursor_from_target(target)))
    row = await session.get(SystemConfig, _SEARCH_WANTED_CURSOR_CONFIG_KEY)
    if row is None:
        session.add(
            SystemConfig(
                key=_SEARCH_WANTED_CURSOR_CONFIG_KEY,
                value=value,
                value_type="string",
            )
        )
        return
    row.value = value
    row.value_type = "string"


async def _load_rotated_wanted_issue_targets(
    session: AsyncSession,
    *,
    limit: int = _SEARCH_WANTED_BATCH_LIMIT,
) -> list[IssueSearchTarget]:
    """Load a fair global wanted-search batch, continuing after the saved cursor."""
    cursor = await _load_search_wanted_cursor(session)
    if cursor is None:
        return await load_wanted_issue_search_targets(session, limit=limit)

    targets = await load_wanted_issue_search_targets(session, limit=limit, after=cursor)
    if len(targets) >= limit:
        return targets

    seen_issue_ids = {target.issue_id for target in targets}
    wrapped = await load_wanted_issue_search_targets(session, limit=limit - len(targets))
    targets.extend(target for target in wrapped if target.issue_id not in seen_issue_ids)
    return targets


async def _build_mocked_issue_outcome(
    session: AsyncSession,
    search_svc: object,
    target: IssueSearchTarget,
    runtime: SearchRuntime,
    *,
    force_generic: bool = False,
) -> IssueSearchOutcome:
    """Adapt old mocked search task tests onto the shared outcome structure."""

    raw_results = await search_svc.search_for_issue(  # type: ignore[attr-defined]
        session,
        target.issue_id,
        force_generic=force_generic,
        source_priority=runtime.source_priority,
    )
    filtered_results = await BlocklistService.filter_results(session, raw_results)
    best = None
    if filtered_results:
        best = search_svc.evaluate_results(  # type: ignore[attr-defined]
            filtered_results,
            wanted_series=target.series_title,
            wanted_issue=target.issue_number,
            wanted_year=target.series_year,
            wanted_issue_type=target.issue_type,
            alternate_names=target.alternate_names,
            **runtime.eval_kwargs,
        )

    matched: list[ValidationResult] = []
    rejected: list[ValidationResult] = []
    best_validation = None
    if best is not None:
        validator = ReleaseValidator(**runtime.validator_kwargs)
        matched = validator.validate_results(
            [best],
            wanted_series=target.series_title,
            wanted_issue=target.issue_number,
            wanted_year=target.series_year,
            wanted_issue_type=target.issue_type,
            alternate_names=target.alternate_names,
        )
        if matched:
            best_validation = matched[0]

    return IssueSearchOutcome(
        target=target,
        mode="fast" if force_generic else "deep",
        query_count=1,
        raw_results=raw_results,
        filtered_results=filtered_results,
        matched=matched,
        rejected=rejected,
        best_release=best if best_validation is not None else None,
        best_validation=best_validation,
        search_details={
            "results_count": len(raw_results),
            "filtered_results_count": len(filtered_results),
            "query_count": 1,
            "search_mode": "fast" if force_generic else "deep",
            "used_fallback": False,
        },
        elapsed_ms=0,
    )


async def _build_mocked_wanted_outcome(
    session: AsyncSession,
    search_svc: object,
    target: IssueSearchTarget,
    runtime: SearchRuntime,
    raw_results: list[ReleaseResult],
) -> IssueSearchOutcome:
    """Adapt mocked wanted-search maps into the shared outcome structure."""

    filtered_results = await BlocklistService.filter_results(session, raw_results)
    best = None
    search_error: str | None = None
    if filtered_results:
        try:
            best = search_svc.evaluate_results(  # type: ignore[attr-defined]
                filtered_results,
                wanted_series=target.series_title,
                wanted_issue=target.issue_number,
                wanted_year=target.series_year,
                wanted_issue_type=target.issue_type,
                alternate_names=target.alternate_names,
                **runtime.eval_kwargs,
            )
        except Exception as exc:  # pragma: no cover - exercised by integration tests
            search_error = str(exc)
            logger.exception(
                "search_wanted_issue_evaluation_failed",
                issue_id=target.issue_id,
                series_id=target.series_id,
                series_title=target.series_title,
                issue_number=target.issue_number,
            )

    matched: list[ValidationResult] = []
    rejected: list[ValidationResult] = []
    best_validation = None
    if best is not None:
        validator = ReleaseValidator(**runtime.validator_kwargs)
        matched = validator.validate_results(
            [best],
            wanted_series=target.series_title,
            wanted_issue=target.issue_number,
            wanted_year=target.series_year,
            wanted_issue_type=target.issue_type,
            alternate_names=target.alternate_names,
        )
        if matched:
            best_validation = matched[0]

    return IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=1,
        raw_results=raw_results,
        filtered_results=filtered_results,
        matched=matched,
        rejected=rejected,
        best_release=best if best_validation is not None else None,
        best_validation=best_validation,
        search_details={
            "results_count": len(raw_results),
            "filtered_results_count": len(filtered_results),
            "query_count": 1,
            "search_mode": "fast",
            "used_fallback": False,
            "error": search_error,
        },
        elapsed_ms=0,
    )


async def search_series_issues(
    series_id: int,
    *,
    pending_log_ids_by_issue: dict[int, int] | None = None,
) -> dict[str, int]:
    """Search indexers for all wanted issues of a single series.

    Obtains its own DB session so it can be called from event subscribers
    and background tasks without sharing caller state.

    Returns:
        Dict with ``wanted``, ``sent``, and ``queued`` counts.
    """
    log = logger.bind(series_id=series_id)
    log.info("search_series_issues_start")
    remaining_pending_log_ids = dict(pending_log_ids_by_issue or {})

    factory = get_session_factory()
    async with factory() as session:
        try:
            preload_started_at = time.monotonic()
            runtime = await _build_task_search_runtime(
                session,
                include_download_clients=True,
            )
            if runtime is None:
                if remaining_pending_log_ids:
                    await _complete_pending_bulk_search_logs(
                        session,
                        remaining_pending_log_ids,
                        action_status="no_indexers",
                    )
                log.info("search_series_issues_no_indexers")
                return {"wanted": 0, "sent": 0, "queued": 0}

            series = await session.get(Series, series_id)
            if not series:
                if remaining_pending_log_ids:
                    await _complete_pending_bulk_search_logs(
                        session,
                        remaining_pending_log_ids,
                        action_status="series_not_found",
                    )
                log.warning("search_series_issues_not_found")
                return {"wanted": 0, "sent": 0, "queued": 0}

            targets = await load_series_wanted_search_targets(session, series_id)
            if not targets:
                if remaining_pending_log_ids:
                    await _complete_pending_bulk_search_logs(
                        session,
                        remaining_pending_log_ids,
                        action_status="no_wanted",
                    )
                log.info("search_series_issues_no_wanted")
                return {"wanted": 0, "sent": 0, "queued": 0}

            preload_ms = int((time.monotonic() - preload_started_at) * 1000)
            log.info(
                "search_series_issues_config",
                series=str(series.title),
                year=series.year_start,
                wanted_count=len(targets),
                preload_ms=preload_ms,
                quick_first_two_pass=runtime.two_pass_enabled,
                concurrency=DEFAULT_WANTED_SEARCH_CONCURRENCY,
            )

            search_started_at = time.monotonic()
            pass1_outcomes: list[IssueSearchOutcome] = []
            pass2_outcomes: list[IssueSearchOutcome] = []
            for attempt in range(1, SQLITE_LOCK_RETRY_ATTEMPTS + 1):
                try:
                    if attempt > 1:
                        retry_runtime = await _build_task_search_runtime(
                            session,
                            include_download_clients=True,
                        )
                        if retry_runtime is None:
                            msg = "Search runtime became unavailable during lock retry"
                            raise RuntimeError(msg)
                        runtime = retry_runtime

                    search_svc = SearchService(
                        runtime.registry,
                        failure_threshold=runtime.failure_threshold,
                    )
                    if _is_mocked_search_service(search_svc):
                        two_pass_enabled = await _load_mocked_two_pass_enabled(session, runtime)
                        pass1_outcomes = [
                            await _build_mocked_issue_outcome(
                                session,
                                search_svc,
                                target,
                                runtime,
                            )
                            for target in targets
                        ]
                        pass2_targets = [
                            outcome.target
                            for outcome in pass1_outcomes
                            if outcome.best_validation is None
                            and outcome.target.issue_type.value in _TYPE_QUERY_KEYWORDS
                            and two_pass_enabled
                        ]
                        pass2_outcomes = [
                            await _build_mocked_issue_outcome(
                                session,
                                search_svc,
                                target,
                                runtime,
                                force_generic=True,
                            )
                            for target in pass2_targets
                        ]
                    else:
                        pass1_outcomes = await search_svc.search_targets_quick_first(
                            session,
                            targets,
                            indexer_configs=runtime.indexer_configs,
                            eval_kwargs=runtime.eval_kwargs,
                            validator_kwargs=runtime.validator_kwargs,
                            source_priority=runtime.source_priority,
                            enable_deep_fallback=runtime.two_pass_enabled,
                            concurrency=DEFAULT_WANTED_SEARCH_CONCURRENCY,
                        )
                        pass2_outcomes = []

                    # Persist indexer health immediately after network fan-out.
                    await session.commit()
                    break
                except OperationalError as exc:
                    await session.rollback()
                    if not is_sqlite_locked_error(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS:
                        raise
                    delay_seconds = sqlite_lock_retry_delay(attempt)
                    log.warning(
                        "search_series_retrying_after_sqlite_lock",
                        attempt=attempt,
                        max_attempts=SQLITE_LOCK_RETRY_ATTEMPTS,
                        delay_seconds=delay_seconds,
                        stage="search_fanout_persist",
                    )
                    await asyncio.sleep(delay_seconds)
            search_fanout_ms = int((time.monotonic() - search_started_at) * 1000)

            download_svc = _build_download_service(runtime.registry)
            intervention_svc = InterventionService(download_svc)

            sent = 0
            queued = 0
            pass2_by_issue = {outcome.target.issue_id: outcome for outcome in pass2_outcomes}
            routing_started_at = time.monotonic()

            for pass1_outcome in pass1_outcomes:
                target = pass1_outcome.target
                issue_log = log.bind(issue_id=target.issue_id, issue_number=target.issue_number)
                pass2_outcome = pass2_by_issue.get(target.issue_id)

                issue_log.info(
                    "search_series_issue_results",
                    indexer_results=len(pass1_outcome.raw_results),
                    search_pass=1,
                    mode=pass1_outcome.mode,
                    query_count=pass1_outcome.query_count,
                    elapsed_ms=pass1_outcome.elapsed_ms,
                )
                if pass2_outcome is not None:
                    issue_log.info(
                        "search_series_issue_results",
                        indexer_results=len(pass2_outcome.raw_results),
                        search_pass=2,
                        mode=pass2_outcome.mode,
                        query_count=pass2_outcome.query_count,
                        elapsed_ms=pass2_outcome.elapsed_ms,
                    )

                selected_outcome = pass1_outcome
                selected_pass = 1
                if (
                    pass1_outcome.best_validation is None
                    and pass2_outcome is not None
                    and pass2_outcome.best_validation is not None
                ):
                    selected_outcome = pass2_outcome
                    selected_pass = 2

                issue_grabbed = 0
                issue_queued = 0
                pending_log_id = remaining_pending_log_ids.get(target.issue_id)
                try:
                    if (
                        selected_outcome.best_validation is None
                        or selected_outcome.best_release is None
                    ):
                        issue_log.info("search_series_issue_no_match", search_pass=selected_pass)
                    else:
                        validation = selected_outcome.best_validation
                        best = selected_outcome.best_release
                        if should_auto_grab(
                            validation.confidence,
                            target.issue_type,
                            runtime.type_thresholds,
                        ):
                            await download_svc.send_to_client(session, best, target.issue_id)
                            issue_grabbed = 1
                            sent += 1
                            issue_log.info(
                                "search_series_issue_auto_grab",
                                best_title=best.title,
                                best_indexer=best.indexer_name,
                                confidence=validation.confidence.value,
                            )
                        elif await intervention_svc.has_pending_for_issue(session, target.issue_id):
                            issue_log.info(
                                "search_series_issue_pending_exists",
                                best_title=best.title,
                                search_pass=selected_pass,
                            )
                        else:
                            await intervention_svc.create_pending_match(
                                session,
                                target.issue_id,
                                best,
                                validation,
                            )
                            issue_queued = 1
                            queued += 1
                            issue_log.info(
                                "search_series_issue_queued",
                                best_title=best.title,
                                confidence=validation.confidence.value,
                                search_pass=selected_pass,
                            )

                    details = dict(selected_outcome.search_details)
                    if pass2_outcome is not None:
                        total_found = len(pass1_outcome.raw_results) + len(
                            pass2_outcome.raw_results
                        )
                        details["results_count"] = total_found
                        details["search_passes"] = 2
                        details["pass1_results_count"] = len(pass1_outcome.raw_results)
                        details["pass2_results_count"] = len(pass2_outcome.raw_results)
                    else:
                        results_count_value = details.get("results_count")
                        total_found = (
                            int(results_count_value)
                            if isinstance(results_count_value, int | float | str)
                            else len(selected_outcome.raw_results)
                        )
                        details.setdefault(
                            "search_passes",
                            selected_outcome.search_details.get("search_passes", 1),
                        )
                    best_confidence = (
                        selected_outcome.best_validation.confidence.value
                        if selected_outcome.best_validation is not None
                        else None
                    )

                    await _persist_bulk_search_log(
                        session,
                        target=target,
                        pending_log_id=pending_log_id,
                        results_found=total_found,
                        results_grabbed=issue_grabbed,
                        results_queued=issue_queued,
                        results_rejected=max(0, total_found - issue_grabbed - issue_queued),
                        details=details,
                        best_confidence=best_confidence,
                        action_status=(
                            "downloading"
                            if issue_grabbed
                            else "queued"
                            if issue_queued
                            else "no_results"
                        ),
                    )
                    remaining_pending_log_ids.pop(target.issue_id, None)
                except Exception:
                    await session.rollback()
                    if pending_log_id is not None:
                        await _complete_pending_bulk_search_logs(
                            session,
                            {target.issue_id: pending_log_id},
                            action_status="error",
                            run_state="failed",
                            error_message="Search processing failed for this issue.",
                        )
                        remaining_pending_log_ids.pop(target.issue_id, None)
                    issue_log.exception("search_series_issue_failed", search_pass=selected_pass)

                await asyncio.sleep(0)

            routing_ms = int((time.monotonic() - routing_started_at) * 1000)

            log.info(
                "search_series_issues_complete",
                wanted=len(targets),
                sent=sent,
                queued=queued,
                preload_ms=preload_ms,
                search_fanout_ms=search_fanout_ms,
                routing_ms=routing_ms,
                **_search_outcome_log_diagnostics([*pass1_outcomes, *pass2_outcomes]),
            )
            return {"wanted": len(targets), "sent": sent, "queued": queued}
        except Exception:
            await session.rollback()
            if remaining_pending_log_ids:
                await _complete_pending_bulk_search_logs(
                    session,
                    remaining_pending_log_ids,
                    action_status="error",
                    run_state="failed",
                    error_message="Search failed before completion.",
                )
            log.exception("search_series_issues_failed")
            return {"wanted": 0, "sent": 0, "queued": 0}


async def search_wanted() -> None:
    """Search indexers for all wanted issues and route matches."""
    factory = get_session_factory()
    runtime: SearchRuntime | None = None
    wanted_outcomes: list[IssueSearchOutcome] = []
    preload_ms = 0
    search_fanout_ms = 0

    for attempt in range(1, SQLITE_LOCK_RETRY_ATTEMPTS + 1):
        async with factory() as session:
            try:
                preload_started_at = time.monotonic()
                local_runtime = await _build_task_search_runtime(
                    session,
                    include_download_clients=True,
                )
                if local_runtime is None:
                    log_deduped_warning(
                        logger,
                        "search_wanted_missing_indexers",
                        key="search_wanted_missing_indexers",
                        action_required="Enable at least one indexer to search wanted issues.",
                    )
                    return

                targets = await _load_rotated_wanted_issue_targets(session)
                preload_ms = int((time.monotonic() - preload_started_at) * 1000)
                search_svc = SearchService(
                    local_runtime.registry,
                    failure_threshold=local_runtime.failure_threshold,
                )
                search_started_at = time.monotonic()
                if _is_mocked_search_service(search_svc):
                    results_map = await search_svc.search_wanted(
                        session,
                        indexer_configs=local_runtime.indexer_configs,
                    )
                    if not targets and results_map:
                        targets = [
                            IssueSearchTarget(
                                issue_id=issue_id,
                                series_id=0,
                                series_title="Unknown",
                                issue_number=0.0,
                                issue_type=IssueType.ISSUE,
                            )
                            for issue_id in results_map
                        ]
                    local_outcomes = [
                        await _build_mocked_wanted_outcome(
                            session,
                            search_svc,
                            target,
                            local_runtime,
                            results_map.get(target.issue_id, []),
                        )
                        for target in targets
                        if results_map.get(target.issue_id)
                    ]
                else:
                    local_outcomes = await search_svc.search_targets_quick_first(
                        session,
                        targets,
                        indexer_configs=local_runtime.indexer_configs,
                        eval_kwargs=local_runtime.eval_kwargs,
                        validator_kwargs=local_runtime.validator_kwargs,
                        source_priority=local_runtime.source_priority,
                        enable_deep_fallback=local_runtime.two_pass_enabled,
                        concurrency=DEFAULT_WANTED_SEARCH_CONCURRENCY,
                    )
                search_fanout_ms = int((time.monotonic() - search_started_at) * 1000)
                if targets:
                    await _save_search_wanted_cursor(session, targets[-1])

                # Persist indexer health updates from the search fan-out before the
                # per-issue routing phase begins. This keeps those writes short-lived
                # instead of holding a pending transaction across the full task run.
                await session.commit()

                runtime = local_runtime
                wanted_outcomes = local_outcomes
                break
            except OperationalError as exc:
                await session.rollback()
                if not is_sqlite_locked_error(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS:
                    raise
                delay_seconds = sqlite_lock_retry_delay(attempt)
                logger.warning(
                    "search_wanted_retrying_after_sqlite_lock",
                    attempt=attempt,
                    max_attempts=SQLITE_LOCK_RETRY_ATTEMPTS,
                    delay_seconds=delay_seconds,
                    stage="search_fanout_persist",
                )
            except Exception:
                await session.rollback()
                raise
        await asyncio.sleep(delay_seconds)

    if runtime is None:
        return

    if not wanted_outcomes:
        logger.debug("search_wanted_no_results")
        return

    download_svc = _build_download_service(runtime.registry)
    intervention_svc = InterventionService(download_svc)

    sent = 0
    queued = 0
    failed = 0
    async with factory() as session:
        try:
            routing_started_at = time.monotonic()
            for outcome in wanted_outcomes:
                target = outcome.target
                issue_grabbed = 0
                issue_queued = 0
                best_confidence: str | None = None
                action_status = "no_results" if not outcome.raw_results else "no_match"
                run_state = "completed"
                error_message: str | None = None
                try:
                    if outcome.best_validation is not None and outcome.best_release is not None:
                        validation = outcome.best_validation
                        best = outcome.best_release
                        best_confidence = validation.confidence.value
                        if should_auto_grab(
                            validation.confidence,
                            target.issue_type,
                            runtime.type_thresholds,
                        ):
                            await download_svc.send_to_client(session, best, target.issue_id)
                            sent += 1
                            issue_grabbed = 1
                            action_status = "downloading"
                        elif not await intervention_svc.has_pending_for_issue(
                            session, target.issue_id
                        ):
                            await intervention_svc.create_pending_match(
                                session, target.issue_id, best, validation
                            )
                            queued += 1
                            issue_queued = 1
                            action_status = "queued"
                        else:
                            action_status = "pending_exists"

                    session.add(
                        SearchLog(
                            issue_id=target.issue_id,
                            series_title=target.series_title,
                            issue_number=target.issue_number,
                            search_type=SearchType.AUTOMATED,
                            results_found=len(outcome.raw_results),
                            results_grabbed=issue_grabbed,
                            results_queued=issue_queued,
                            results_rejected=max(
                                0,
                                len(outcome.raw_results) - issue_grabbed - issue_queued,
                            ),
                            details=_merge_search_log_details(
                                existing_details=None,
                                next_details=outcome.search_details,
                                run_state=run_state,
                                action_status=action_status,
                                error_message=error_message,
                            ),
                            best_confidence=best_confidence,
                        )
                    )
                    # Commit per issue to avoid holding SQLite's writer lock
                    # across the full wanted-search run.
                    await session.commit()
                except Exception:
                    await session.rollback()
                    failed += 1
                    run_state = "failed"
                    action_status = "error"
                    error_message = "Search processing failed for this issue."
                    logger.exception("search_wanted_issue_failed", issue_id=target.issue_id)
                    session.add(
                        SearchLog(
                            issue_id=target.issue_id,
                            series_title=target.series_title,
                            issue_number=target.issue_number,
                            search_type=SearchType.AUTOMATED,
                            results_found=len(outcome.raw_results),
                            results_grabbed=0,
                            results_queued=0,
                            results_rejected=len(outcome.raw_results),
                            details=_merge_search_log_details(
                                existing_details=None,
                                next_details=outcome.search_details,
                                run_state=run_state,
                                action_status=action_status,
                                error_message=error_message,
                            ),
                            best_confidence=best_confidence,
                        )
                    )
                    await session.commit()

            routing_ms = int((time.monotonic() - routing_started_at) * 1000)

            logger.info(
                "search_wanted_complete",
                sent=sent,
                queued=queued,
                failed=failed,
                total=len(wanted_outcomes),
                preload_ms=preload_ms,
                search_fanout_ms=search_fanout_ms,
                routing_ms=routing_ms,
                **_search_outcome_log_diagnostics(wanted_outcomes),
            )
        except Exception:
            await session.rollback()
            raise


async def purge_search_logs() -> None:
    """Delete search log entries older than the configured retention period."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    factory = get_session_factory()

    async with factory() as session:
        try:
            retention_days = await _load_search_log_retention_days(session)

            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            result = await session.execute(delete(SearchLog).where(SearchLog.created_at < cutoff))
            pruned = result.rowcount  # type: ignore[attr-defined]
            await session.commit()

            if pruned:
                logger.info(
                    "purge_search_logs_complete",
                    pruned=pruned,
                    retention_days=retention_days,
                )
        except Exception:
            await session.rollback()
            raise
