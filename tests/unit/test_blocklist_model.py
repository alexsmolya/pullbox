"""
Unit tests for BlocklistEntry model, BlocklistReason enum, and normalize_release_title.

Covers normalization edge cases, enum values, model field storage,
unique constraints, and foreign key behavior.

Run:
    pytest tests/unit/test_blocklist_model.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from pullbox.models.blocklist import (
    BlocklistEntry,
    BlocklistReason,
    normalize_release_title,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def make_entry() -> (
    callable  # type: ignore[type-arg]
):
    """Factory fixture for creating BlocklistEntry instances."""

    def _make(
        title: str = "Batman.018.2026.Digital.Zone-Empire",
        reason: BlocklistReason = BlocklistReason.FAILED,
        **kwargs: object,
    ) -> BlocklistEntry:
        return BlocklistEntry(
            release_title=title,
            release_title_normalized=normalize_release_title(title),
            reason=reason,
            **kwargs,
        )

    return _make


# ── normalize_release_title tests ─────────────────────────────────────


class TestNormalizeReleaseTitle:
    """Tests for normalize_release_title() — core normalization function."""

    def test_lowercases(self) -> None:
        result = normalize_release_title("Batman.018.2026.Digital.Zone-Empire")
        assert result == "batman.018.2026.digital.zone-empire"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert normalize_release_title("  Saga 073  ") == "saga 073"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_release_title("Batman   018   2026") == "batman 018 2026"

    def test_handles_tabs_and_newlines(self) -> None:
        assert normalize_release_title("Batman\t018\n2026") == "batman 018 2026"

    def test_empty_string(self) -> None:
        assert normalize_release_title("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_release_title("   ") == ""

    def test_unicode_preserved(self) -> None:
        assert normalize_release_title("Château 001") == "château 001"

    def test_mixed_case_special_chars(self) -> None:
        assert normalize_release_title("X-MEN #12 (2026)") == "x-men #12 (2026)"

    def test_very_long_title_no_truncation(self) -> None:
        long_title = "A" * 500
        result = normalize_release_title(long_title)
        assert len(result) == 500
        assert result == "a" * 500

    def test_only_special_characters(self) -> None:
        assert normalize_release_title("---...___") == "---...___"


# ── BlocklistReason enum tests ────────────────────────────────────────


class TestBlocklistReason:
    """Tests for BlocklistReason enum."""

    def test_has_exactly_three_values(self) -> None:
        assert len(BlocklistReason) == 3

    def test_values_are_lowercase_strings(self) -> None:
        assert BlocklistReason.FAILED.value == "failed"
        assert BlocklistReason.REJECTED.value == "rejected"
        assert BlocklistReason.MANUAL.value == "manual"

    def test_is_str_enum(self) -> None:
        """StrEnum values are also valid strings."""
        assert isinstance(BlocklistReason.FAILED, str)
        assert BlocklistReason.FAILED == "failed"


# ── BlocklistEntry model tests ────────────────────────────────────────


@pytest.mark.slow
class TestBlocklistEntryCreation:
    """Tests for BlocklistEntry ORM model creation and field storage."""

    async def test_creation_with_required_fields(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry()
        db_session.add(entry)
        await db_session.flush()

        assert entry.id is not None
        assert entry.release_title == "Batman.018.2026.Digital.Zone-Empire"
        assert entry.reason == BlocklistReason.FAILED

    async def test_normalized_title_set_on_creation(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(title="Batman.018.2026.Digital.Zone-Empire")
        db_session.add(entry)
        await db_session.flush()

        assert entry.release_title_normalized == "batman.018.2026.digital.zone-empire"

    async def test_creation_with_all_optional_fields_none(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(
            download_url=None,
            series_id=None,
            issue_id=None,
            indexer_id=None,
            error_message=None,
            release_group=None,
            download_history_id=None,
        )
        db_session.add(entry)
        await db_session.flush()

        assert entry.id is not None
        assert entry.download_url is None
        assert entry.series_id is None
        assert entry.issue_id is None
        assert entry.indexer_id is None
        assert entry.error_message is None
        assert entry.release_group is None
        assert entry.download_history_id is None

    async def test_creation_with_all_fields_populated(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(
            title="Saga.073.2026.Minutemen",
            reason=BlocklistReason.REJECTED,
            download_url="https://example.com/nzb/12345",
            error_message="Failed to extract archive",
            release_group="Minutemen",
        )
        db_session.add(entry)
        await db_session.flush()

        assert entry.id is not None
        assert entry.download_url == "https://example.com/nzb/12345"
        assert entry.error_message == "Failed to extract archive"
        assert entry.release_group == "Minutemen"

    async def test_timestamps_auto_populated(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(title="Test Timestamps")
        db_session.add(entry)
        await db_session.flush()

        assert entry.created_at is not None
        assert entry.updated_at is not None

    async def test_id_auto_incremented(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        e1 = make_entry(title="First Entry")
        e2 = make_entry(title="Second Entry")
        db_session.add_all([e1, e2])
        await db_session.flush()

        assert e1.id is not None
        assert e2.id is not None
        assert e2.id > e1.id


@pytest.mark.slow
class TestBlocklistEntryConstraints:
    """Tests for unique index and foreign key behavior."""

    async def test_multiple_entries_different_titles(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        for title in ["Batman 018", "Saga 073", "X-Men 012"]:
            db_session.add(make_entry(title=title))
        await db_session.flush()

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        assert len(entries) == 3

    async def test_reason_enum_stored_correctly(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        for reason in BlocklistReason:
            db_session.add(make_entry(title=f"Test {reason.value}", reason=reason))
        await db_session.flush()

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        reasons = {e.reason for e in entries}
        assert reasons == set(BlocklistReason)

    async def test_fk_series_allows_null(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(series_id=None)
        db_session.add(entry)
        await db_session.flush()
        assert entry.series_id is None

    async def test_fk_issue_allows_null(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(issue_id=None)
        db_session.add(entry)
        await db_session.flush()
        assert entry.issue_id is None

    async def test_fk_indexer_allows_null(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(indexer_id=None)
        db_session.add(entry)
        await db_session.flush()
        assert entry.indexer_id is None

    async def test_fk_download_history_allows_null(
        self,
        db_session: AsyncSession,
        make_entry: callable,  # type: ignore[type-arg]
    ) -> None:
        entry = make_entry(download_history_id=None)
        db_session.add(entry)
        await db_session.flush()
        assert entry.download_history_id is None
