"""Issue API routes — detail, status updates, search, download, and file import."""

import time
from dataclasses import dataclass
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import inspect, select
from sqlalchemy.orm import joinedload

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.exceptions import ConfigurationError, NotFoundError
from pullbox.core.file_ops import register_library_file
from pullbox.core.file_safety import classify_resource_safety_exception
from pullbox.models.download import DownloadState
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import LibraryFile, MatchConfidence
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.schemas.issue import (
    IssueFileDeleteResponse,
    IssueResponse,
    IssueUpdate,
    ManualFileImportProgressResponse,
    ManualFileImportRequest,
    ManualFileImportResponse,
)
from pullbox.schemas.search import (
    GrabReleaseRequest,
    GrabReleaseResponse,
    InteractiveSearchIssue,
    InteractiveSearchResponse,
    MatchDetails,
    RejectedResultItem,
    SearchResultItem,
)
from pullbox.services.issue_file_service import (
    delete_issue_library_file,
    resolve_configured_utility_trash_dir,
)
from pullbox.services.issue_import_service import (
    ManualIssueImportError,
    prepare_manual_issue_import,
)
from pullbox.services.issue_service import IssueService
from pullbox.services.release_validator import (
    ValidationResult,
)
from pullbox.services.search_service import (
    DEFAULT_TYPE_THRESHOLDS,
    IssueSearchOutcome,
    IssueSearchTarget,
    SearchRuntime,
    SearchService,
    build_search_runtime,
    load_issue_search_target,
    score_release,
    should_auto_grab,
    summarize_search_pass,
)
from pullbox.services.search_types import SearchEvalKwargs
from pullbox.tasks.issue_import_task import (
    cancel_issue_import_run,
    get_issue_import_progress_state,
    start_issue_import_run,
)

logger = structlog.get_logger(__name__)


router = APIRouter(prefix="/issues", tags=["issues"])


# ── Helpers ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _IssueSearchBundle:
    """Shared search execution payload for issue-scoped search routes."""

    target: IssueSearchTarget
    issue: InteractiveSearchIssue
    runtime: SearchRuntime | None
    outcome: IssueSearchOutcome | None
    matched_items: list["SearchResultItem"]
    rejected_items: list["RejectedResultItem"]
    search_time_ms: int


async def _increment_search_log_grabbed(
    session: DbSession,
    *,
    issue_id: int,
    search_log_id: int | None,
) -> None:
    """Increment the grabbed counter for the originating manual search row."""
    if search_log_id is None:
        return

    search_log = await session.get(SearchLog, search_log_id)
    if search_log is None:
        logger.warning(
            "issue_manual_grab_search_log_missing",
            issue_id=issue_id,
            search_log_id=search_log_id,
        )
        return

    if search_log.issue_id != issue_id:
        logger.warning(
            "issue_manual_grab_search_log_issue_mismatch",
            issue_id=issue_id,
            search_log_id=search_log_id,
            search_log_issue_id=search_log.issue_id,
        )
        return

    search_log.results_grabbed = int(search_log.results_grabbed or 0) + 1


def _enrich_issue(issue: Issue) -> dict[str, object]:
    """Add computed fields (series_title, has_file) to an issue."""
    mapper = inspect(type(issue))
    data: dict[str, object] = {c.key: getattr(issue, c.key) for c in mapper.columns}
    data["series_title"] = issue.series.title if issue.series else None
    data["has_file"] = issue.library_file is not None
    return data


async def _load_issue_response(session: DbSession, issue_id: int) -> IssueResponse:
    """Load an issue with relationships and return a validated response."""
    result = await session.execute(
        select(Issue)
        .options(joinedload(Issue.series), joinedload(Issue.library_file))
        .where(Issue.id == issue_id)
    )
    issue = result.unique().scalar_one_or_none()
    if issue is None:
        raise NotFoundError("Issue", issue_id)
    return IssueResponse.model_validate(_enrich_issue(issue))


_CONFIDENCE_BONUS = {
    MatchConfidence.HIGH: 100,
    MatchConfidence.MEDIUM: 70,
    MatchConfidence.LOW: 40,
}


def build_interactive_results(
    matched_vr: list[ValidationResult],
    rejected_vr: list[ValidationResult],
    eval_kwargs: SearchEvalKwargs,
    source_priority: list[str] | None = None,
    *,
    issue_type: IssueType = IssueType.ISSUE,
    type_thresholds: dict[str, str] | None = None,
) -> tuple[list[SearchResultItem], list[RejectedResultItem]]:
    """Build schema objects from validation results with quality scoring.

    Extracts the scoring and schema-construction logic so it can be
    tested independently of the async endpoint / ASGI transport.

    Returns:
        A tuple of (matched_items, rejected_items) ready for the response.
    """
    min_score = eval_kwargs.get("min_score", 10.0)
    confidence_blend = eval_kwargs.get("confidence_blend", 0.40)
    quality_weight = 1.0 - confidence_blend
    score_weights = eval_kwargs.get("score_weights")
    min_size_mb = eval_kwargs.get("min_size_mb")
    max_size_mb = eval_kwargs.get("max_size_mb")
    preferred_format = eval_kwargs.get("preferred_format")
    seeder_tiers = eval_kwargs.get("seeder_tiers")

    matched_items: list[SearchResultItem] = []
    for vr in matched_vr:
        quality = score_release(
            vr.release,
            min_size_mb=int(str(min_size_mb)) if min_size_mb else 50,
            max_size_mb=int(str(max_size_mb)) if max_size_mb else 2000,
            preferred_format=str(preferred_format) if preferred_format else None,
            seeder_tiers=seeder_tiers,
            score_weights=score_weights,
        )
        bonus = _CONFIDENCE_BONUS.get(vr.confidence, 0)
        final_score = (quality * quality_weight) + (bonus * confidence_blend)

        matched_items.append(
            SearchResultItem(
                title=vr.release.title,
                indexer_name=vr.release.indexer_name,
                download_url=vr.release.download_url,
                info_url=vr.release.info_url,
                size_bytes=vr.release.size_bytes,
                age_days=vr.release.age_days,
                seeders=vr.release.seeders,
                leechers=vr.release.leechers,
                is_torrent=vr.release.is_torrent,
                category=vr.release.category,
                confidence=str(vr.confidence.value),
                quality_score=round(final_score, 1),
                auto_grabbable=final_score >= min_score
                and should_auto_grab(
                    vr.confidence,
                    issue_type,
                    DEFAULT_TYPE_THRESHOLDS if type_thresholds is None else type_thresholds,
                ),
                match_details=MatchDetails(
                    parsed_series=vr.parsed.series_name,
                    parsed_issue=vr.parsed.issue_number,
                    parsed_year=vr.parsed.year,
                    series_similarity=round(vr.series_similarity, 3),
                    match_type=vr.match_type,
                ),
            )
        )

    rejected_items: list[RejectedResultItem] = []
    for vr in rejected_vr:
        rejected_items.append(
            RejectedResultItem(
                title=vr.release.title,
                indexer_name=vr.release.indexer_name,
                download_url=vr.release.download_url,
                info_url=vr.release.info_url,
                size_bytes=vr.release.size_bytes,
                age_days=vr.release.age_days,
                seeders=vr.release.seeders,
                leechers=vr.release.leechers,
                is_torrent=vr.release.is_torrent,
                category=vr.release.category,
                rejection_reason=vr.rejection_reason or "unknown",
                confidence=str(vr.confidence.value) if vr.is_match else None,
            )
        )

    # Sort matched results by source priority (stable — preserves score order within protocol)
    if source_priority:
        priority_map = {proto: idx for idx, proto in enumerate(source_priority)}
        default_rank = len(source_priority)
        matched_items.sort(
            key=lambda item: priority_map.get(
                "torrent" if item.is_torrent else "usenet",
                default_rank,
            )
        )

    return matched_items, rejected_items


def _build_issue_context(target: IssueSearchTarget) -> InteractiveSearchIssue:
    """Build the public issue context returned by interactive search responses."""

    return InteractiveSearchIssue(
        id=target.issue_id,
        series_title=target.series_title,
        issue_number=target.issue_number,
        issue_type=target.issue_type.value,
        year=target.series_year,
    )


def _build_manual_file_import_response(
    *,
    issue_id: int,
    library_file: LibraryFile,
) -> ManualFileImportResponse:
    """Build the API response for a completed manual file import."""
    lf = library_file
    return ManualFileImportResponse(
        issue_id=issue_id,
        library_file_id=lf.id,
        file_name=lf.file_name,
        file_path=lf.file_path,
        file_size=lf.file_size,
        file_format=str(lf.file_format.value)
        if hasattr(lf.file_format, "value")
        else str(lf.file_format),
        match_confidence=str(lf.match_confidence.value)
        if isinstance(lf.match_confidence, MatchConfidence)
        else str(lf.match_confidence),
    )


async def _run_issue_search(
    session: DbSession,
    issue_id: int,
    *,
    include_download_clients: bool,
) -> _IssueSearchBundle:
    """Run the shared search pipeline for an issue and shape UI/API payloads."""

    started_at = time.monotonic()
    target = await load_issue_search_target(session, issue_id)
    if target is None:
        raise NotFoundError("Issue", issue_id)

    issue_ctx = _build_issue_context(target)
    runtime = await build_search_runtime(
        session,
        include_download_clients=include_download_clients,
    )
    # Release the read transaction before slow indexer/network work. Search log
    # persistence happens later in a short write transaction owned by the caller.
    await session.commit()
    if runtime is None:
        return _IssueSearchBundle(
            target=target,
            issue=issue_ctx,
            runtime=None,
            outcome=None,
            matched_items=[],
            rejected_items=[],
            search_time_ms=int((time.monotonic() - started_at) * 1000),
        )

    search_svc = SearchService(
        registry=runtime.registry,
        failure_threshold=runtime.failure_threshold,
    )
    outcome = await search_svc.search_issue_target(
        session,
        target,
        mode="fast",
        indexer_configs=runtime.indexer_configs,
        eval_kwargs=runtime.eval_kwargs,
        validator_kwargs=runtime.validator_kwargs,
        source_priority=runtime.source_priority,
    )
    # Blocklist filtering/config reads can open a transaction after the indexer
    # call. Release it before any deep fallback work or UI response building.
    await session.commit()
    if outcome.matched or not runtime.two_pass_enabled:
        outcome.search_details["search_strategy"] = (
            "quick_first" if outcome.matched else "quick_first_single_pass"
        )
    else:
        fast_summary = summarize_search_pass(outcome)
        outcome = await search_svc.search_issue_target(
            session,
            target,
            mode="deep",
            indexer_configs=runtime.indexer_configs,
            eval_kwargs=runtime.eval_kwargs,
            validator_kwargs=runtime.validator_kwargs,
            source_priority=runtime.source_priority,
            auto_fallback=True,
        )
        # Deep fallback performs the same DB-backed filtering after network IO.
        # The caller will persist search history separately.
        await session.commit()
        outcome.search_details["search_strategy"] = "quick_first_deep_fallback"
        outcome.search_details["fast_search"] = fast_summary
    outcome.search_details["manual_search_strategy"] = outcome.search_details.get("search_strategy")
    matched_items, rejected_items = build_interactive_results(
        outcome.matched,
        outcome.rejected,
        runtime.eval_kwargs,
        source_priority=runtime.source_priority,
        issue_type=target.issue_type,
        type_thresholds=runtime.type_thresholds,
    )
    return _IssueSearchBundle(
        target=target,
        issue=issue_ctx,
        runtime=runtime,
        outcome=outcome,
        matched_items=matched_items,
        rejected_items=rejected_items,
        search_time_ms=int((time.monotonic() - started_at) * 1000),
    )


def _build_issue_search_log(
    bundle: _IssueSearchBundle,
    *,
    search_type: SearchType = SearchType.MANUAL,
    results_grabbed: int = 0,
    results_queued: int = 0,
    results_rejected: int | None = None,
    action_status: str | None = None,
    run_state: str = "completed",
) -> SearchLog:
    """Create a search history row from a shared search bundle."""

    outcome = bundle.outcome
    if outcome is None:
        details: dict[str, object] = {"results_count": 0, "validated_count": 0}
        results_found = 0
        best_confidence = None
    else:
        details = dict(outcome.search_details)
        details["validated_count"] = len(bundle.matched_items)
        results_found = len(outcome.raw_results)
        best_confidence = (
            outcome.best_validation.confidence.value
            if outcome.best_validation is not None
            else None
        )

    details["run_state"] = run_state
    details["search_time_ms"] = bundle.search_time_ms
    if action_status:
        details["action_status"] = action_status
    if results_rejected is None:
        results_rejected = len(bundle.rejected_items)

    return SearchLog(
        issue_id=bundle.target.issue_id,
        series_title=bundle.target.series_title,
        issue_number=bundle.target.issue_number,
        search_type=search_type,
        results_found=results_found,
        results_grabbed=results_grabbed,
        results_queued=results_queued,
        results_rejected=results_rejected,
        details=details,
        best_confidence=best_confidence,
    )


# ── Detail ────────────────────────────────────────────────────────────


@router.get("/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> IssueResponse:
    """Get full issue detail by ID."""
    return await _load_issue_response(session, issue_id)


# ── Update ────────────────────────────────────────────────────────────


@router.put("/{issue_id}", response_model=IssueResponse)
async def update_issue(
    issue_id: int,
    body: IssueUpdate,
    _user: AuthenticatedUser,
    session: DbSession,
) -> IssueResponse:
    """Update an issue's status or metadata."""
    if body.status is not None:
        await IssueService.mark_status(session, issue_id, body.status)
    return await _load_issue_response(session, issue_id)


# ── Actions ───────────────────────────────────────────────────────────


@router.post("/{issue_id}/search", status_code=200)
async def search_issue(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> dict[str, object]:
    """Trigger a manual search for a specific issue.

    Returns validated results with confidence scoring. Uses the same
    validation pipeline as the interactive search endpoint.
    """
    bundle = await _run_issue_search(
        session,
        issue_id,
        include_download_clients=False,
    )
    if bundle.runtime is None:
        return {"issue_id": issue_id, "results": [], "error": "no indexers configured"}

    session.add(_build_issue_search_log(bundle))
    await session.commit()

    logger.info("issue_manual_search", issue_id=issue_id, results=len(bundle.matched_items))
    return {
        "issue_id": issue_id,
        "results": [
            {
                "title": item.title,
                "indexer_name": item.indexer_name,
                "size_bytes": item.size_bytes,
                "age_days": item.age_days,
                "is_torrent": item.is_torrent,
                "confidence": item.confidence,
            }
            for item in bundle.matched_items
        ],
    }


@router.get("/{issue_id}/search-results", response_model=InteractiveSearchResponse)
async def get_search_results(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> InteractiveSearchResponse:
    """Return validated search results for interactive display.

    Searches all configured indexers for the issue and returns both matched
    and rejected results with full context (confidence, match details,
    rejection reasons) so the UI can present an interactive search results page.
    """
    bundle = await _run_issue_search(
        session,
        issue_id,
        include_download_clients=False,
    )
    if bundle.runtime is None:
        return InteractiveSearchResponse(
            issue=bundle.issue,
            matched=[],
            rejected=[],
            search_time_ms=bundle.search_time_ms,
            search_log_id=None,
        )

    search_log = _build_issue_search_log(bundle)
    session.add(search_log)
    await session.commit()

    logger.info(
        "issue_interactive_search",
        issue_id=issue_id,
        matched=len(bundle.matched_items),
        rejected=len(bundle.rejected_items),
        search_time_ms=bundle.search_time_ms,
    )

    return InteractiveSearchResponse(
        issue=bundle.issue,
        matched=bundle.matched_items,
        rejected=bundle.rejected_items,
        search_time_ms=bundle.search_time_ms,
        search_log_id=search_log.id,
    )


@router.post("/{issue_id}/grab", status_code=201)
async def grab_release(
    issue_id: int,
    body: GrabReleaseRequest,
    _user: AuthenticatedUser,
    session: DbSession,
) -> GrabReleaseResponse:
    """Grab a specific release for an issue.

    Bypasses automated matching — the user has already selected the release.
    Constructs a ReleaseResult and sends it directly to the download client.
    """
    from pullbox.composition.services import build_domain_download_service

    issue_result = await session.execute(
        select(Issue).options(joinedload(Issue.library_file)).where(Issue.id == issue_id)
    )
    issue = issue_result.unique().scalar_one_or_none()
    if not issue:
        raise NotFoundError("Issue", issue_id)
    replace_existing_file = issue.library_file is not None

    built = await build_domain_download_service(session)
    if built is None:
        from pullbox.core.exceptions import ProviderError

        raise ProviderError("download", "No download clients configured")

    download_svc, _indexer_configs = built

    download = await download_svc.grab_release(
        session,
        issue_id=issue_id,
        download_url=body.download_url,
        title=body.title,
        indexer_name=body.indexer_name,
        is_torrent=body.is_torrent,
        file_size=body.file_size,
        replace_existing_file=replace_existing_file,
    )
    if download.state == DownloadState.FAILED:
        detail = download.error_message or "Download client rejected the release."
        await session.commit()
        logger.warning(
            "issue_manual_grab_failed",
            issue_id=issue_id,
            download_id=download.id,
            title=body.title,
            is_torrent=body.is_torrent,
            error=detail,
            manual=True,
        )
        raise HTTPException(status_code=502, detail=detail)

    await _increment_search_log_grabbed(
        session,
        issue_id=issue_id,
        search_log_id=body.search_log_id,
    )

    logger.info(
        "issue_manual_grab",
        issue_id=issue_id,
        download_id=download.id,
        title=body.title,
        is_torrent=body.is_torrent,
        manual=True,
    )

    return GrabReleaseResponse(
        issue_id=issue_id,
        download_id=download.id,
        title=body.title,
        status=str(download.state.value),
    )


@router.post("/{issue_id}/download", status_code=200)
async def download_issue(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> dict[str, object]:
    """Search for and download the best available release for an issue.

    Respects per-type confidence thresholds: if the best match does not
    meet the auto-grab threshold for its issue type, it is queued to the
    intervention queue instead of being sent directly to the client.
    """
    from pullbox.composition.services import build_download_service
    from pullbox.services.intervention_service import InterventionService

    # Verify issue exists
    issue = await session.get(Issue, issue_id)
    if not issue:
        raise NotFoundError("Issue", issue_id)

    issue_was_skipped = issue.status == IssueStatus.SKIPPED

    bundle = await _run_issue_search(
        session,
        issue_id,
        include_download_clients=True,
    )
    # Searching a skipped issue implicitly marks it as wanted. Do this after
    # the search setup transaction has been released so slow indexer calls do
    # not hold a write transaction open.
    if issue_was_skipped:
        issue.status = IssueStatus.WANTED
    if bundle.runtime is None:
        session.add(
            _build_issue_search_log(
                bundle,
                search_type=SearchType.AUTOMATED,
                action_status="no_clients",
                results_rejected=0,
            )
        )
        await session.commit()
        return {"issue_id": issue_id, "status": "no_clients", "error": "no indexers configured"}

    download_svc = build_download_service(bundle.runtime.registry)

    if (
        bundle.outcome is None
        or bundle.outcome.best_release is None
        or bundle.outcome.best_validation is None
    ):
        session.add(
            _build_issue_search_log(
                bundle,
                search_type=SearchType.AUTOMATED,
                action_status="no_results",
                results_rejected=0,
            )
        )
        await session.commit()
        logger.info("issue_download_no_results", issue_id=issue_id)
        return {"issue_id": issue_id, "status": "no_results"}

    validation = bundle.outcome.best_validation
    best = bundle.outcome.best_release

    # Check threshold — auto-grab or queue to intervention
    if should_auto_grab(
        validation.confidence,
        bundle.target.issue_type,
        bundle.runtime.type_thresholds,
    ):
        download = await download_svc.send_to_client(session, best, issue_id)
        session.add(
            _build_issue_search_log(
                bundle,
                search_type=SearchType.AUTOMATED,
                results_grabbed=1,
                results_rejected=max(0, len(bundle.outcome.raw_results) - 1),
                action_status="downloading",
            )
        )
        await session.commit()
        logger.info(
            "issue_download_started",
            issue_id=issue_id,
            download_id=download.id,
            title=best.title,
            confidence=validation.confidence.value,
        )
        return {
            "issue_id": issue_id,
            "status": "downloading",
            "download_id": download.id,
            "release_title": best.title,
        }

    # Below threshold — queue to intervention
    intervention_svc = InterventionService(download_service=download_svc)
    if await intervention_svc.has_pending_for_issue(session, issue_id):
        session.add(
            _build_issue_search_log(
                bundle,
                search_type=SearchType.AUTOMATED,
                results_rejected=max(0, len(bundle.outcome.raw_results) - 1),
                action_status="queued_existing",
            )
        )
        await session.commit()
        logger.info(
            "issue_download_pending_exists",
            issue_id=issue_id,
            best_title=best.title,
        )
        return {
            "issue_id": issue_id,
            "status": "queued",
            "release_title": best.title,
            "message": "Already queued for review",
        }

    await intervention_svc.create_pending_match(
        session,
        issue_id,
        best,
        validation,
    )
    session.add(
        _build_issue_search_log(
            bundle,
            search_type=SearchType.AUTOMATED,
            results_queued=1,
            results_rejected=max(0, len(bundle.outcome.raw_results) - 1),
            action_status="queued",
        )
    )
    await session.commit()
    logger.info(
        "issue_download_queued",
        issue_id=issue_id,
        title=best.title,
        confidence=validation.confidence.value,
    )
    return {
        "issue_id": issue_id,
        "status": "queued",
        "release_title": best.title,
        "confidence": validation.confidence.value,
    }


@router.post(
    "/{issue_id}/import-file",
    status_code=201,
    response_model=ManualFileImportResponse,
)
async def import_file_for_issue(
    issue_id: int,
    body: ManualFileImportRequest,
    _user: AuthenticatedUser,
    session: DbSession,
) -> ManualFileImportResponse:
    """Manually import a local file for a specific issue.

    Validates the file exists and has a supported comic format, then
    delegates to ``register_library_file()`` for move/rename/registration.
    """
    try:
        prepared = await prepare_manual_issue_import(
            session,
            issue_id=issue_id,
            file_path=body.file_path,
            move_to_library=body.move_to_library,
        )
        existing_library_file = getattr(prepared.issue, "__dict__", {}).get("library_file")
        library_file = await register_library_file(
            session,
            source_path=prepared.source_path,
            issue=prepared.issue,
            confidence=MatchConfidence.MANUAL,
            move_to_library=True,
            library_root_id=prepared.issue.series.library_root_id,
            loaded_issue=prepared.issue,
            ingest_policy=prepared.ingest_policy,
            allow_resource_safety_exception=body.allow_resource_safety_exception,
            replace_existing_library_file=existing_library_file is not None,
            replacement_trash_dir=await resolve_configured_utility_trash_dir(session)
            if existing_library_file is not None
            else None,
        )
    except ManualIssueImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        resource_block = classify_resource_safety_exception(exc)
        if resource_block is not None:
            raise HTTPException(status_code=409, detail=resource_block.reason) from exc
        raise

    logger.info(
        "issue_file_imported",
        issue_id=issue_id,
        library_file_id=library_file.id,
        file_name=library_file.file_name,
        transfer_method=prepared.ingest_policy.post_processing_method,
    )

    return _build_manual_file_import_response(
        issue_id=issue_id,
        library_file=library_file,
    )


@router.delete(
    "/{issue_id}/file",
    response_model=IssueFileDeleteResponse,
)
async def delete_file_for_issue(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> IssueFileDeleteResponse:
    """Delete or trash the library file linked to an issue."""
    result = await delete_issue_library_file(session, issue_id)
    logger.info(
        "issue_file_deleted",
        issue_id=result.issue_id,
        status=result.status.value,
        file_deleted=result.file_deleted,
        trashed=result.trashed,
    )
    return IssueFileDeleteResponse(
        issue_id=result.issue_id,
        status=result.status,
        file_deleted=result.file_deleted,
        trashed=result.trashed,
        trash_path=str(result.trash_path) if result.trash_path is not None else None,
    )


@router.post(
    "/{issue_id}/import-file/start",
    status_code=202,
    response_model=ManualFileImportProgressResponse,
)
async def start_import_file_for_issue(
    issue_id: int,
    body: ManualFileImportRequest,
    _user: AuthenticatedUser,
) -> ManualFileImportProgressResponse:
    """Start a background manual import for the issue-detail UI."""
    return await start_issue_import_run(issue_id, body)


@router.post(
    "/{issue_id}/import-file/cancel",
    response_model=ManualFileImportProgressResponse,
)
async def cancel_import_file_for_issue(
    issue_id: int,
    _user: AuthenticatedUser,
) -> ManualFileImportProgressResponse:
    """Cancel a background manual import for the issue-detail UI."""
    return await cancel_issue_import_run(issue_id)


@router.get(
    "/{issue_id}/import-file/progress",
    response_model=ManualFileImportProgressResponse,
)
async def get_import_file_for_issue_progress(
    issue_id: int,
    _user: AuthenticatedUser,
) -> ManualFileImportProgressResponse:
    """Return the latest live progress snapshot for one manual issue import."""
    progress = get_issue_import_progress_state(issue_id)
    if progress is not None:
        return progress
    return ManualFileImportProgressResponse(
        issue_id=issue_id,
    )


# ── File Download ────────────────────────────────────────────────────


@router.get("/{issue_id}/download-file")
async def download_issue_file(
    issue_id: int,
    _user: AuthenticatedUser,
    session: DbSession,
) -> FileResponse:
    """Download the comic file for an owned issue."""
    result = await session.execute(
        select(Issue).options(joinedload(Issue.library_file)).where(Issue.id == issue_id)
    )
    issue = result.unique().scalar_one_or_none()
    if issue is None:
        raise NotFoundError("Issue", issue_id)

    if issue.library_file is None:
        raise HTTPException(status_code=404, detail="No file available for this issue")

    file_path = Path(issue.library_file.file_path)
    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File no longer exists on disk",
        )

    return FileResponse(
        path=file_path,
        filename=issue.library_file.file_name,
        media_type="application/octet-stream",
    )
