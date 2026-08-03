"""Private manifest and revisioned page endpoints for the embedded reader."""

from __future__ import annotations

from typing import Annotated, Never

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from pullbox.api.deps import AuthenticatedStreamUser, get_request_session_factory
from pullbox.config import get_settings
from pullbox.core.page_sources import PageSourceError, PageSourceErrorCode, ReaderResourceLimits
from pullbox.schemas.reader import (
    ReaderManifestResponse,
    ReaderProgressResponse,
    ReaderProgressUpdate,
)
from pullbox.services.reader_content_service import (
    ReaderContentService,
    ResolvedReaderSource,
    StaleReaderRevisionError,
    load_reader_source_record,
    resolve_reader_source,
)
from pullbox.services.reader_state_service import (
    ReaderStateValidationError,
    load_reader_state,
    update_reader_state,
)

router = APIRouter(prefix="/reader", tags=["reader"], include_in_schema=False)

_ERROR_STATUS = {
    PageSourceErrorCode.MISSING_FILE: 404,
    PageSourceErrorCode.UNSUPPORTED_FORMAT: 415,
    PageSourceErrorCode.FORMAT_MISMATCH: 422,
    PageSourceErrorCode.CORRUPT_SOURCE: 422,
    PageSourceErrorCode.EMPTY_SOURCE: 422,
    PageSourceErrorCode.PAGE_OUT_OF_RANGE: 404,
    PageSourceErrorCode.RESOURCE_LIMIT: 413,
    PageSourceErrorCode.RENDERER_UNAVAILABLE: 503,
}


def _content_service(request: Request) -> ReaderContentService:
    app = request.app
    service = getattr(app.state, "reader_content_service", None)
    if isinstance(service, ReaderContentService):
        return service
    settings = get_settings()
    service = ReaderContentService(
        cache_dir=settings.data_dir / "reader-cache",
        limits=ReaderResourceLimits(
            max_entries=settings.reader_max_entries,
            max_page_bytes=settings.reader_max_page_mb * 1024 * 1024,
            max_total_uncompressed_bytes=settings.reader_max_expanded_mb * 1024 * 1024,
            max_compression_ratio=settings.reader_max_compression_ratio,
            max_image_pixels=settings.reader_max_image_pixels,
            pdf_dpi=settings.reader_pdf_dpi,
        ),
        max_open_sources=settings.reader_open_source_cache_size,
        max_cache_bytes=settings.reader_cache_max_mb * 1024 * 1024,
    )
    app.state.reader_content_service = service
    return service


async def _resolved_source(request: Request, issue_id: int) -> ResolvedReaderSource:
    factory = get_request_session_factory(request)
    try:
        async with factory() as session:
            record = await load_reader_source_record(session, issue_id)
        return await anyio.to_thread.run_sync(resolve_reader_source, record, abandon_on_cancel=True)
    except PageSourceError as exc:
        _raise_http_error(exc)


def _raise_http_error(exc: PageSourceError) -> Never:
    raise HTTPException(
        status_code=_ERROR_STATUS[exc.code],
        detail={"code": exc.code.value, "message": str(exc)},
    ) from exc


@router.get("/issues/{issue_id}/manifest", response_model=ReaderManifestResponse)
async def reader_manifest(
    request: Request,
    issue_id: int,
    _user: AuthenticatedStreamUser,
) -> JSONResponse:
    """Return a side-effect-free reader manifest after closing the DB session."""
    source = await _resolved_source(request, issue_id)
    try:
        manifest = await _content_service(request).get_manifest(source)
    except PageSourceError as exc:
        _raise_http_error(exc)
    factory = get_request_session_factory(request)
    async with factory() as session:
        state = await load_reader_state(session, user_id=_user.id, issue_id=issue_id)
    initial_page_index = 0
    if (
        state is not None
        and state.content_revision == manifest.revision
        and state.page_count == manifest.page_count
    ):
        initial_page_index = min(state.last_page_index, manifest.page_count - 1)
    response = ReaderManifestResponse(
        issue_id=manifest.issue_id,
        title=manifest.title,
        issue_label=manifest.issue_label,
        format=manifest.format,
        page_count=manifest.page_count,
        revision=manifest.revision,
        initial_page_index=initial_page_index,
        page_url_template=(
            f"/api/v1/reader/issues/{issue_id}/pages/{{page_index}}?revision={manifest.revision}"
        ),
        progress_url=f"/api/v1/reader/issues/{issue_id}/progress",
    )
    return JSONResponse(
        content=response.model_dump(mode="json"),
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/issues/{issue_id}/pages/{page_index}")
async def reader_page(
    request: Request,
    issue_id: int,
    page_index: int,
    _user: AuthenticatedStreamUser,
    revision: Annotated[str, Query(min_length=1, max_length=64)],
) -> Response:
    """Stream one immutable cached page without a request-scoped DB session."""
    source = await _resolved_source(request, issue_id)
    try:
        page = await _content_service(request).get_page(
            source,
            page_index=page_index,
            revision=revision,
        )
    except StaleReaderRevisionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_revision", "message": "The comic file has changed."},
        ) from exc
    except PageSourceError as exc:
        _raise_http_error(exc)

    headers = {
        "Cache-Control": "private, max-age=3600, immutable",
        "ETag": page.etag,
    }
    if request.headers.get("if-none-match") == page.etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path=page.path, media_type=page.media_type, headers=headers)


@router.put(
    "/issues/{issue_id}/progress",
    response_model=ReaderProgressResponse,
)
async def reader_progress(
    request: Request,
    issue_id: int,
    payload: ReaderProgressUpdate,
    user: AuthenticatedStreamUser,
) -> ReaderProgressResponse:
    """Persist an explicit settled page without coupling state to page GETs."""
    source = await _resolved_source(request, issue_id)
    try:
        manifest = await _content_service(request).get_manifest(source)
    except PageSourceError as exc:
        _raise_http_error(exc)
    factory = get_request_session_factory(request)
    try:
        async with factory() as session:
            snapshot = await update_reader_state(
                session,
                user_id=user.id,
                issue_id=issue_id,
                revision=payload.revision,
                page_index=payload.page_index,
                page_count=payload.page_count,
                completion_candidate=payload.completion_candidate,
                expected_revision=manifest.revision,
                expected_page_count=manifest.page_count,
            )
            await session.commit()
    except ReaderStateValidationError as exc:
        status_code = 409 if exc.code in {"stale_revision", "page_count_mismatch"} else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return ReaderProgressResponse(
        page_index=snapshot.last_page_index,
        page_count=snapshot.page_count,
        revision=snapshot.content_revision,
        completed_at=snapshot.completed_at,
        updated_at=snapshot.updated_at,
    )
