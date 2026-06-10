"""Import job Server-Sent Events helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from fastapi.responses import StreamingResponse

from pullbox.api.deps import get_request_session_factory
from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import ImportJob, ImportJobStatus
from pullbox.schemas.import_job import ImportProgressEvent
from pullbox.utilities.sse import SSEEvent, subscribe

if TYPE_CHECKING:
    from fastapi import Request

HEARTBEAT_SSE_FRAME = 'data: {"heartbeat": true}\n\n'
SSE_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
IMPORT_STREAM_TERMINAL_STATUSES = {
    ImportJobStatus.REVIEW.value,
    ImportJobStatus.COMPLETED.value,
    ImportJobStatus.FAILED.value,
    ImportJobStatus.CANCELLED.value,
    ImportJobStatus.ROLLED_BACK.value,
}

SubscribeFn = Callable[[str], Any]


def is_import_stream_terminal_status(status: str | ImportJobStatus) -> bool:
    """Return True when a progress stream should stop after this status."""
    value = status.value if isinstance(status, ImportJobStatus) else str(status)
    return value in IMPORT_STREAM_TERMINAL_STATUSES


def build_initial_import_progress_sse(
    job_id: int,
    job: Any,
) -> tuple[str | None, bool]:
    """Format a cached progress snapshot as an initial SSE frame."""
    initial_snapshot = dict(job.progress_snapshot or {}) if job is not None else {}
    if not initial_snapshot:
        return None, False

    cached_event = ImportProgressEvent.model_validate(
        {
            **initial_snapshot,
            "job_id": job_id,
            "status": str(initial_snapshot.get("status") or (job.status.value if job else "")),
        }
    )
    return (
        SSEEvent(
            channel=f"import:{job_id}",
            event_type="progress",
            data=cached_event.model_dump(mode="json"),
        ).format_sse(),
        is_import_stream_terminal_status(cached_event.status),
    )


async def load_initial_import_progress_sse(
    request: Request,
    job_id: int,
) -> tuple[str | None, bool]:
    """Return the cached progress event without holding a session during streaming."""
    factory = get_request_session_factory(request)
    async with factory() as session:
        job = await session.get(ImportJob, job_id)
        return build_initial_import_progress_sse(job_id, job)


async def ensure_import_job_exists_for_stream(request: Request, job_id: int) -> None:
    """Validate stream jobs with a short-lived session before opening SSE."""
    factory = get_request_session_factory(request)
    async with factory() as session:
        job = await session.get(ImportJob, job_id)
        if job is None:
            raise NotFoundError("ImportJob", job_id)


async def iter_import_progress_sse(
    job_id: int,
    *,
    initial_event: str | None = None,
    initial_is_terminal: bool = False,
    subscribe_fn: SubscribeFn = subscribe,
    timeout_seconds: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Yield progress SSE frames for an import job."""
    if initial_event:
        yield initial_event
        if initial_is_terminal:
            return

    async with subscribe_fn(f"import:{job_id}") as queue:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                if event is None:
                    break
                yield event.format_sse()
                status = str(event.data.get("status") or "")
                if is_import_stream_terminal_status(status):
                    break
            except TimeoutError:
                yield HEARTBEAT_SSE_FRAME


async def iter_import_log_sse(
    job_id: int,
    *,
    subscribe_fn: SubscribeFn = subscribe,
    timeout_seconds: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Yield log SSE frames for an import job."""
    async with subscribe_fn(f"import:{job_id}") as queue:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                if event is None:
                    break
                if event.event_type == "log":
                    yield event.format_sse()
            except TimeoutError:
                yield HEARTBEAT_SSE_FRAME


def make_sse_streaming_response(
    generator: AsyncGenerator[str, None],
) -> StreamingResponse:
    """Wrap an SSE generator in the app's standard streaming response."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
