"""System log API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse  # noqa: TC002

from pullbox.api.deps import DbSession, InteractiveOperatorUser  # noqa: TC001
from pullbox.api.v1.system_logs import (
    LogContentResponse,
    LogFileResponse,
    build_log_download_response,
    build_log_stream_response,
    clear_log_paths,
    delete_log_path,
    list_log_file_responses,
    read_log_content,
)
from pullbox.config import get_settings

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)

router = APIRouter()


async def _get_logs_dir(session: DbSession) -> Path:
    """Read the runtime logs directory."""
    return get_settings().logs_dir


@router.get("/logs", response_model=list[LogFileResponse])
async def list_log_files(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> list[LogFileResponse]:
    """List all log files in the logs directory."""
    logs_dir = await _get_logs_dir(session)
    return list_log_file_responses(logs_dir)


@router.get("/logs/{filename}/content", response_model=LogContentResponse)
async def view_log_file(
    filename: str,
    _user: InteractiveOperatorUser,
    session: DbSession,
    tail: int = Query(500, ge=1, le=10000, description="Number of lines from the end to return"),
) -> LogContentResponse:
    """Read the contents of a log file.

    Returns the last *tail* lines by default. Set tail to a large value
    to retrieve the full file.
    """
    logs_dir = await _get_logs_dir(session)
    return read_log_content(logs_dir, filename, tail=tail)


@router.get("/logs/{filename}/download")
async def download_log_file(
    filename: str,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> FileResponse:
    """Download a log file."""
    logs_dir = await _get_logs_dir(session)
    return build_log_download_response(logs_dir, filename)


@router.delete("/logs/{filename}")
async def delete_log_file(
    filename: str,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> dict[str, str]:
    """Delete a specific log file."""
    logs_dir = await _get_logs_dir(session)
    response = delete_log_path(logs_dir, filename)
    logger.info("log_file_deleted", filename=filename)
    return response


@router.get("/logs/{filename}/stream")
async def stream_log_file(
    filename: str,
    request: Request,
    _user: InteractiveOperatorUser,
    session: DbSession,
    level: str = Query("all", pattern="^(all|debug|info|warning|error)$"),
) -> StreamingResponse:
    """Stream new log lines via Server-Sent Events (tail -f style).

    Sends existing last 50 lines on connect, then polls for new lines.
    """
    logs_dir = await _get_logs_dir(session)
    return build_log_stream_response(logs_dir, filename, request, level=level)


@router.delete("/logs")
async def clear_log_files(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> dict[str, str]:
    """Delete all log files."""
    logs_dir = await _get_logs_dir(session)
    response = clear_log_paths(logs_dir)
    logger.info("log_files_cleared", message=response["message"])
    return response
