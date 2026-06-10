"""
Unit tests for BlocklistService core CRUD operations.

Covers add_entry (happy path, duplicates, edge cases), remove_entry,
remove_entries (bulk), get_entry, list_entries (pagination, filtering,
search), and count_entries.

Run:
    pytest tests/unit/test_blocklist_service.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, inspect

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series
from pullbox.services.blocklist_service import BlocklistService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SelectRecorder:
    """Capture SELECT statements executed against an async engine."""

    def __init__(self, async_engine) -> None:
        self._engine = async_engine.sync_engine
        self.statements: list[str] = []

    def __enter__(self) -> SelectRecorder:
        event.listen(self._engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._record)

    def _record(
        self,
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self.statements.append(statement)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def svc() -> BlocklistService:
    """BlocklistService instance."""
    return BlocklistService()


@pytest.fixture()
async def seed_entries(db_session: AsyncSession) -> list[BlocklistEntry]:
    """Seed 25 blocklist entries: 10 FAILED, 10 REJECTED, 5 MANUAL.

    Uses series_id=None to avoid FK constraints on the series table
    which may not have test data in unit test context.
    """
    entries: list[BlocklistEntry] = []
    reasons = (
        [BlocklistReason.FAILED] * 10
        + [BlocklistReason.REJECTED] * 10
        + [BlocklistReason.MANUAL] * 5
    )
    for i, reason in enumerate(reasons):
        title = f"Release.{i:03d}.2026.Digital.Group{i % 3}"
        entry = BlocklistEntry(
            release_title=title,
            release_title_normalized=normalize_release_title(title),
            reason=reason,
            release_group=f"Group{i % 3}",
        )
        db_session.add(entry)
        entries.append(entry)
    await db_session.flush()
    return entries


# ── add_entry tests ───────────────────────────────────────────────────


@pytest.mark.slow
class TestAddEntry:
    """Tests for BlocklistService.add_entry()."""

    async def test_happy_path_creates_entry(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.add_entry(
            db_session,
            "Batman.018.2026.Digital.Zone-Empire",
            BlocklistReason.FAILED,
        )
        assert result is not None
        assert result.id is not None
        assert result.release_title == "Batman.018.2026.Digital.Zone-Empire"
        assert result.release_title_normalized == "batman.018.2026.digital.zone-empire"
        assert result.reason == BlocklistReason.FAILED

    async def test_stores_optional_fields(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.add_entry(
            db_session,
            "Saga.073.2026.Minutemen",
            BlocklistReason.REJECTED,
            download_url="https://example.com/nzb/123",
            error_message="Extraction failed",
            release_group="Minutemen",
        )
        assert result is not None
        assert result.download_url == "https://example.com/nzb/123"
        assert result.error_message == "Extraction failed"
        assert result.release_group == "Minutemen"

    async def test_returns_entry_with_id(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.add_entry(db_session, "Test Title", BlocklistReason.MANUAL)
        assert result is not None
        assert isinstance(result.id, int)
        assert result.id > 0

    async def test_duplicate_exact_title_returns_none(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        result = await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.MANUAL)
        assert result is None

    async def test_duplicate_different_case_returns_none(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        result = await svc.add_entry(db_session, "BATMAN.018.2026", BlocklistReason.FAILED)
        assert result is None

    async def test_duplicate_extra_whitespace_returns_none(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman 018 2026", BlocklistReason.FAILED)
        result = await svc.add_entry(db_session, "Batman  018  2026", BlocklistReason.FAILED)
        assert result is None

    async def test_duplicate_different_url_returns_none(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(
            db_session,
            "Batman.018",
            BlocklistReason.FAILED,
            download_url="https://a.com",
        )
        result = await svc.add_entry(
            db_session,
            "Batman.018",
            BlocklistReason.FAILED,
            download_url="https://b.com",
        )
        assert result is None

    async def test_two_different_titles_both_created(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        r1 = await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        r2 = await svc.add_entry(db_session, "Saga.073", BlocklistReason.FAILED)
        assert r1 is not None
        assert r2 is not None
        assert r1.id != r2.id

    async def test_max_length_title(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        long_title = "A" * 500
        result = await svc.add_entry(db_session, long_title, BlocklistReason.MANUAL)
        assert result is not None
        assert len(result.release_title) == 500

    async def test_whitespace_only_title_handled(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.add_entry(db_session, "   ", BlocklistReason.MANUAL)
        # Should either create with empty normalized title or return None
        # Either is acceptable — just shouldn't raise
        assert result is None or result.release_title_normalized == ""

    async def test_all_optional_fields_none(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.add_entry(db_session, "Test", BlocklistReason.MANUAL)
        assert result is not None
        assert result.download_url is None
        assert result.series_id is None
        assert result.issue_id is None


# ── remove_entry tests ────────────────────────────────────────────────


@pytest.mark.slow
class TestRemoveEntry:
    """Tests for BlocklistService.remove_entry()."""

    async def test_removes_existing_entry(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        entry = await svc.add_entry(db_session, "To Remove", BlocklistReason.MANUAL)
        assert entry is not None
        result = await svc.remove_entry(db_session, entry.id)
        assert result is True

    async def test_returns_false_for_nonexistent(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.remove_entry(db_session, 99999)
        assert result is False

    async def test_returns_false_for_zero(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.remove_entry(db_session, 0)
        assert result is False

    async def test_returns_false_for_negative(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.remove_entry(db_session, -1)
        assert result is False

    async def test_entry_gone_after_removal(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        entry = await svc.add_entry(db_session, "Gone After", BlocklistReason.MANUAL)
        assert entry is not None
        await svc.remove_entry(db_session, entry.id)
        gone = await svc.get_entry(db_session, entry.id)
        assert gone is None


# ── remove_entries (bulk) tests ───────────────────────────────────────


@pytest.mark.slow
class TestRemoveEntries:
    """Tests for BlocklistService.remove_entries() — bulk removal."""

    async def test_removes_multiple(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        e1 = await svc.add_entry(db_session, "Bulk 1", BlocklistReason.MANUAL)
        e2 = await svc.add_entry(db_session, "Bulk 2", BlocklistReason.MANUAL)
        e3 = await svc.add_entry(db_session, "Bulk 3", BlocklistReason.MANUAL)
        assert e1 and e2 and e3
        count = await svc.remove_entries(db_session, [e1.id, e2.id, e3.id])
        assert count == 3

    async def test_returns_zero_for_empty_list(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        count = await svc.remove_entries(db_session, [])
        assert count == 0

    async def test_returns_zero_when_none_exist(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        count = await svc.remove_entries(db_session, [99998, 99999])
        assert count == 0

    async def test_mixed_existing_and_nonexistent(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        entry = await svc.add_entry(db_session, "Mixed", BlocklistReason.MANUAL)
        assert entry is not None
        count = await svc.remove_entries(db_session, [entry.id, 99999])
        assert count == 1


# ── get_entry tests ──────────────────────────────────────────────────


@pytest.mark.slow
class TestGetEntry:
    """Tests for BlocklistService.get_entry()."""

    async def test_returns_existing_entry(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        created = await svc.add_entry(db_session, "Get Me", BlocklistReason.MANUAL)
        assert created is not None
        result = await svc.get_entry(db_session, created.id)
        assert result is not None
        assert result.id == created.id
        assert result.release_title == "Get Me"

    async def test_eager_loads_display_relationships(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        series = Series(
            title="Absolute Flash",
            sort_title="absolute flash",
            year_start=2026,
        )
        issue = Issue(
            series=series,
            issue_number=1.0,
            status=IssueStatus.WANTED,
        )
        indexer = IndexerConfig(
            name="MyAnonaMouse",
            indexer_type=IndexerType.TORZNAB,
            url="https://example.test/torznab",
            api_key="secret",
        )
        db_session.add_all([series, issue, indexer])
        await db_session.flush()

        created = await svc.add_entry(
            db_session,
            "Absolute Flash 001 (2026) (Digital) (Zone-Empire)",
            BlocklistReason.MANUAL,
            series_id=series.id,
            issue_id=issue.id,
            indexer_id=indexer.id,
        )
        assert created is not None
        entry_id = created.id
        db_session.expunge_all()

        result = await svc.get_entry(db_session, entry_id)

        assert result is not None
        assert {"series", "issue", "indexer"}.isdisjoint(inspect(result).unloaded)
        assert result.series is not None
        assert result.series.title == "Absolute Flash"
        assert result.issue is not None
        assert result.issue.issue_number == 1.0
        assert result.indexer is not None
        assert result.indexer.name == "MyAnonaMouse"

    async def test_returns_none_for_nonexistent(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.get_entry(db_session, 99999)
        assert result is None

    async def test_returns_none_for_zero(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        result = await svc.get_entry(db_session, 0)
        assert result is None


# ── list_entries tests ────────────────────────────────────────────────


@pytest.mark.slow
class TestListEntries:
    """Tests for BlocklistService.list_entries() — pagination and filtering."""

    async def test_empty_database(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        entries, total = await svc.list_entries(db_session)
        assert entries == []
        assert total == 0

    async def test_default_pagination(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session)
        assert total == 25
        assert len(entries) == 25  # default limit=50 > 25 entries

    async def test_limit_10(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, limit=10)
        assert len(entries) == 10
        assert total == 25

    async def test_offset_20(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, limit=10, offset=20)
        assert len(entries) == 5
        assert total == 25

    async def test_offset_beyond_total(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, limit=10, offset=30)
        assert len(entries) == 0
        assert total == 25

    async def test_limit_zero_returns_empty(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, limit=0)
        assert len(entries) == 0
        assert total == 25

    async def test_display_relationship_access_does_not_add_per_entry_queries(
        self,
        async_engine,
        db_session: AsyncSession,
        svc: BlocklistService,
    ) -> None:
        for i in range(5):
            series = Series(
                title=f"Absolute Flash {i}",
                sort_title=f"absolute flash {i}",
                year_start=2026,
            )
            issue = Issue(
                series=series,
                issue_number=float(i + 1),
                status=IssueStatus.WANTED,
            )
            indexer = IndexerConfig(
                name=f"MyAnonaMouse {i}",
                indexer_type=IndexerType.TORZNAB,
                url=f"https://example.test/{i}/torznab",
                api_key="secret",
            )
            entry = BlocklistEntry(
                release_title=f"Absolute Flash {i + 1:03d} (2026) (Digital)",
                release_title_normalized=normalize_release_title(
                    f"Absolute Flash {i + 1:03d} (2026) (Digital)"
                ),
                reason=BlocklistReason.MANUAL,
                series=series,
                issue=issue,
                indexer=indexer,
            )
            db_session.add(entry)
        await db_session.flush()
        db_session.expunge_all()

        with SelectRecorder(async_engine) as recorder:
            entries, total = await svc.list_entries(db_session, limit=5, sort="series")
            rendered_values = [
                (
                    entry.series.title if entry.series else None,
                    entry.issue.issue_number if entry.issue else None,
                    entry.indexer.name if entry.indexer else None,
                )
                for entry in entries
            ]

        assert total == 5
        assert len(rendered_values) == 5
        assert len(recorder.statements) == 2


@pytest.mark.slow
class TestListEntriesFilterByReason:
    """Tests for list_entries() filtering by reason."""

    async def test_filter_failed(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, reason=BlocklistReason.FAILED)
        assert total == 10
        assert all(e.reason == BlocklistReason.FAILED for e in entries)

    async def test_filter_rejected(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, reason=BlocklistReason.REJECTED)
        assert total == 10
        assert all(e.reason == BlocklistReason.REJECTED for e in entries)

    async def test_filter_manual(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        entries, total = await svc.list_entries(db_session, reason=BlocklistReason.MANUAL)
        assert total == 5
        assert all(e.reason == BlocklistReason.MANUAL for e in entries)

    async def test_no_filter_returns_all(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        _entries, total = await svc.list_entries(db_session, reason=None)
        assert total == 25


@pytest.mark.slow
class TestListEntriesFilterBySeries:
    """Tests for list_entries() filtering by series_id.

    Uses series_id=None since the unit test DB has no series records.
    The filter logic is still exercised via nonexistent ID and None checks.
    """

    async def test_nonexistent_series(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        entries, total = await svc.list_entries(db_session, series_id=99999)
        assert entries == []
        assert total == 0

    async def test_filter_none_series_returns_all(
        self,
        db_session: AsyncSession,
        svc: BlocklistService,
        seed_entries: list[BlocklistEntry],
    ) -> None:
        _entries, total = await svc.list_entries(db_session, series_id=None)
        assert total == 25

    async def test_combined_reason_and_nonexistent_series(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Test Combined", BlocklistReason.FAILED)
        entries, total = await svc.list_entries(
            db_session, reason=BlocklistReason.FAILED, series_id=99999
        )
        assert total == 0
        assert entries == []


@pytest.mark.slow
class TestListEntriesSearch:
    """Tests for list_entries() search by title."""

    async def test_search_matches_case_insensitive(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(
            db_session,
            "Batman.018.2026.Digital.Zone-Empire",
            BlocklistReason.FAILED,
        )
        _entries, total = await svc.list_entries(db_session, search="batman")
        assert total == 1

    async def test_search_partial_match(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(
            db_session,
            "Batman.018.2026.Digital.Zone-Empire",
            BlocklistReason.FAILED,
        )
        _entries, total = await svc.list_entries(db_session, search="empire")
        assert total == 1

    async def test_search_no_match(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        entries, total = await svc.list_entries(db_session, search="xyz")
        assert total == 0
        assert entries == []

    async def test_search_empty_string_returns_all(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        _entries, total = await svc.list_entries(db_session, search="")
        assert total == 1

    async def test_search_none_returns_all(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        _entries, total = await svc.list_entries(db_session, search=None)
        assert total == 1

    async def test_search_combined_with_reason(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        await svc.add_entry(db_session, "Batman.019", BlocklistReason.MANUAL)
        entries, total = await svc.list_entries(
            db_session, search="batman", reason=BlocklistReason.FAILED
        )
        assert total == 1
        assert entries[0].reason == BlocklistReason.FAILED


# ── count_entries tests ───────────────────────────────────────────────


@pytest.mark.slow
class TestCountEntries:
    """Tests for BlocklistService.count_entries()."""

    async def test_empty_table(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        count = await svc.count_entries(db_session)
        assert count == 0

    async def test_after_adding(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Count 1", BlocklistReason.MANUAL)
        await svc.add_entry(db_session, "Count 2", BlocklistReason.MANUAL)
        count = await svc.count_entries(db_session)
        assert count == 2

    async def test_after_removing(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        entry = await svc.add_entry(db_session, "Count Remove", BlocklistReason.MANUAL)
        assert entry is not None
        await svc.add_entry(db_session, "Count Keep", BlocklistReason.MANUAL)
        await svc.remove_entry(db_session, entry.id)
        count = await svc.count_entries(db_session)
        assert count == 1
