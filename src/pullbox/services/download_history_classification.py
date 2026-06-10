"""Shared query helpers for download and post-processing history classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, not_, or_

from pullbox.models.download import DownloadHistory, DownloadState

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


def cancelled_download_clause() -> ColumnElement[bool]:
    """Match user-cancelled download rows."""
    return and_(
        DownloadHistory.state == DownloadState.FAILED,
        DownloadHistory.error_message == "Cancelled by user",
    )


def post_processing_success_clause() -> ColumnElement[bool]:
    """Match rows that completed download and imported into the library."""
    return or_(
        DownloadHistory.state == DownloadState.IMPORTED,
        and_(
            DownloadHistory.state == DownloadState.COMPLETED,
            DownloadHistory.imported_at.is_not(None),
        ),
    )


def post_processing_failure_clause() -> ColumnElement[bool]:
    """Match failed post-processing runs after the download completed."""
    return and_(
        DownloadHistory.state == DownloadState.FAILED,
        DownloadHistory.downloaded_path.is_not(None),
        or_(
            DownloadHistory.error_message.is_(None),
            DownloadHistory.error_message != "Cancelled by user",
        ),
    )


def download_history_clause() -> ColumnElement[bool]:
    """Match rows that belong in download history, not post-processing history."""
    return or_(
        and_(
            DownloadHistory.state == DownloadState.COMPLETED,
            DownloadHistory.imported_at.is_(None),
        ),
        and_(
            DownloadHistory.state == DownloadState.FAILED,
            not_(post_processing_failure_clause()),
        ),
    )


def post_processing_history_clause() -> ColumnElement[bool]:
    """Match imported rows and processing failures for the post-processing page."""
    return or_(
        post_processing_success_clause(),
        post_processing_failure_clause(),
    )
