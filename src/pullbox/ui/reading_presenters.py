"""Presentation models for private reading surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.ui.formatters import format_issue_number

if TYPE_CHECKING:
    from pullbox.services.reading_query_service import ReadingIssueRecord


@dataclass(frozen=True, slots=True)
class ReadingIssueCardView:
    """One reusable, path-free card for the dashboard and Reading workspace."""

    issue_id: int
    series_id: int
    series_title: str
    issue_label: str
    issue_title: str | None
    cover_url: str | None
    readable: bool
    state_label: str
    progress_percent: int
    primary_label: str
    primary_url: str
    completion_action_label: str | None
    completion_action_value: bool | None
    queue_action_label: str
    queue_action_value: bool
    completed: bool
    want_to_read: bool
    density: str


def present_reading_issue(
    record: ReadingIssueRecord,
    *,
    density: str = "workspace",
) -> ReadingIssueCardView:
    """Convert a query projection into the canonical reading-card contract."""
    state = record.state
    state_label = _state_label(record)
    primary_label = _primary_label(record)
    primary_url = (
        f"/issues/{record.issue_id}?read=1" if record.readable else f"/issues/{record.issue_id}"
    )
    completion_action_label: str | None
    completion_action_value: bool | None
    if not record.readable:
        completion_action_label = None
        completion_action_value = None
    elif state.is_completed:
        completion_action_label = "Mark unread"
        completion_action_value = False
    else:
        completion_action_label = "Mark read"
        completion_action_value = True

    return ReadingIssueCardView(
        issue_id=record.issue_id,
        series_id=record.series_id,
        series_title=record.series_title,
        issue_label=f"#{format_issue_number(record.issue_number)}",
        issue_title=record.issue_title,
        cover_url=(
            record.issue_cover_path
            or record.issue_cover_url
            or record.series_cover_path
            or record.series_cover_url
        ),
        readable=record.readable,
        state_label=state_label,
        progress_percent=state.position_percent,
        primary_label=primary_label,
        primary_url=primary_url,
        completion_action_label=completion_action_label,
        completion_action_value=completion_action_value,
        queue_action_label=(
            "Remove from Want to Read" if state.want_to_read else "Add to Want to Read"
        ),
        queue_action_value=not state.want_to_read,
        completed=state.is_completed,
        want_to_read=state.want_to_read,
        density=density,
    )


def present_reading_issues(
    records: tuple[ReadingIssueRecord, ...],
    *,
    density: str = "workspace",
) -> tuple[ReadingIssueCardView, ...]:
    """Present a bounded tuple without leaking ORM or content details."""
    return tuple(present_reading_issue(record, density=density) for record in records)


def _state_label(record: ReadingIssueRecord) -> str:
    state = record.state
    if state.is_completed:
        return "Read"
    if not record.readable and state.want_to_read:
        return "File unavailable"
    if state.has_progress and state.last_page_index is not None and state.page_count is not None:
        position = f"Page {state.last_page_index + 1} of {state.page_count}"
        if state.is_explicitly_unread and state.last_page_index >= state.page_count - 1:
            return f"{position} · Unread"
        return f"{position} · {state.position_percent}%"
    if state.want_to_read:
        return "Not started"
    return "Unread"


def _primary_label(record: ReadingIssueRecord) -> str:
    if not record.readable:
        return "Open issue"
    if record.state.is_completed:
        return "Read again"
    if record.state.is_continue_candidate:
        return "Continue"
    return "Read"
