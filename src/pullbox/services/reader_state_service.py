"""Explicit private resume and deliberate-completion state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pullbox.models.reader import IssueReaderState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ReaderStateValidationError(Exception):
    """Raised when a progress write does not match the current content contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ReaderStateSnapshot:
    """Detached private reader state safe to use after the DB session closes."""

    last_page_index: int | None
    content_revision: str | None
    page_count: int | None
    completed_at: datetime | None
    updated_at: datetime


async def load_reader_state(
    session: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
) -> ReaderStateSnapshot | None:
    """Load one user's state for one issue without mutating it."""
    result = await session.execute(
        select(IssueReaderState).where(
            IssueReaderState.user_id == user_id,
            IssueReaderState.issue_id == issue_id,
        )
    )
    state = result.scalar_one_or_none()
    return _snapshot(state) if state is not None else None


async def update_reader_state(
    session: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    revision: str,
    page_index: int,
    page_count: int,
    completion_candidate: bool,
    expected_revision: str,
    expected_page_count: int,
) -> ReaderStateSnapshot:
    """Validate and persist one explicit settled-page update."""
    _validate_update(
        revision=revision,
        page_index=page_index,
        page_count=page_count,
        completion_candidate=completion_candidate,
        expected_revision=expected_revision,
        expected_page_count=expected_page_count,
    )
    now = datetime.now(UTC)
    completed_at = now if completion_candidate else None
    dialect_name = session.get_bind().dialect.name
    statement: Any
    if dialect_name == "sqlite":
        statement = sqlite_insert(IssueReaderState)
    elif dialect_name == "postgresql":
        statement = postgresql_insert(IssueReaderState)
    else:  # pragma: no cover - Pullbox supports SQLite and PostgreSQL only
        raise RuntimeError(f"Unsupported reader-state database dialect: {dialect_name}")
    statement = statement.values(
        user_id=user_id,
        issue_id=issue_id,
        last_page_index=page_index,
        content_revision=revision,
        page_count=page_count,
        completed_at=completed_at,
        updated_at=now,
    )
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[IssueReaderState.user_id, IssueReaderState.issue_id],
        set_={
            "last_page_index": excluded.last_page_index,
            "content_revision": excluded.content_revision,
            "page_count": excluded.page_count,
            "completed_at": case(
                (
                    IssueReaderState.content_revision != excluded.content_revision,
                    excluded.completed_at,
                ),
                (
                    and_(
                        excluded.completed_at.is_not(None),
                        IssueReaderState.completed_at.is_(None),
                    ),
                    excluded.completed_at,
                ),
                else_=IssueReaderState.completed_at,
            ),
            "updated_at": excluded.updated_at,
        },
    ).returning(IssueReaderState)
    result = await session.execute(statement)
    state = result.scalar_one()
    return _snapshot(state)


def _validate_update(
    *,
    revision: str,
    page_index: int,
    page_count: int,
    completion_candidate: bool,
    expected_revision: str,
    expected_page_count: int,
) -> None:
    if revision != expected_revision:
        raise ReaderStateValidationError("stale_revision", "The comic file has changed.")
    if page_count != expected_page_count or page_count <= 0:
        raise ReaderStateValidationError("page_count_mismatch", "The comic page count changed.")
    if page_index < 0 or page_index >= page_count:
        raise ReaderStateValidationError("page_out_of_range", "The settled page is invalid.")
    if completion_candidate and page_index != page_count - 1:
        raise ReaderStateValidationError(
            "completion_not_final",
            "Completion can only be recorded on the final page.",
        )


def _snapshot(state: IssueReaderState) -> ReaderStateSnapshot:
    return ReaderStateSnapshot(
        last_page_index=state.last_page_index,
        content_revision=state.content_revision,
        page_count=state.page_count,
        completed_at=state.completed_at,
        updated_at=state.updated_at,
    )
