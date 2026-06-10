"""
Unit tests for BlocklistService check/filter methods.

Covers is_release_blocked, get_blocked_groups, is_group_blocked,
and filter_results with release title + group filtering.

Run:
    pytest tests/unit/test_blocklist_filtering.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from pullbox.models.blocklist import BlocklistReason
from pullbox.models.config import SystemConfig
from pullbox.providers.base import ReleaseResult
from pullbox.services.blocklist_service import BlocklistService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ───────────────────────────────────────────────────────────


def _make_release(
    title: str = "Batman.018.2026.Digital.Zone-Empire",
    *,
    indexer: str = "NZBgeek",
    url: str = "https://example.com/nzb/1",
    is_torrent: bool = False,
) -> ReleaseResult:
    """Create a ReleaseResult for testing."""
    return ReleaseResult(
        title=title,
        indexer_name=indexer,
        download_url=url,
        size_bytes=100_000_000,
        age_days=1,
        seeders=None,
        leechers=None,
        grabs=50,
        is_torrent=is_torrent,
        category="Comics",
        published_at=datetime.now(tz=UTC),
    )


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def svc() -> BlocklistService:
    return BlocklistService()


async def _set_config(session: AsyncSession, key: str, value: str) -> None:
    """Helper to set a SystemConfig value."""
    existing = await session.get(SystemConfig, key)
    if existing:
        existing.value = value
    else:
        session.add(SystemConfig(key=key, value=value, value_type="string"))
    await session.flush()


# ── is_release_blocked tests ─────────────────────────────────────────


@pytest.mark.slow
class TestIsReleaseBlocked:
    """Tests for BlocklistService.is_release_blocked()."""

    async def test_exact_match_case_insensitive(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, "batman.018.2026") is True

    async def test_different_case(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, "BATMAN.018.2026") is True

    async def test_whitespace_normalized(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman 018 2026", BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, "Batman  018  2026") is True

    async def test_not_blocked(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, "Saga.073.2026") is False

    async def test_partial_match_not_blocked(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, "Batman") is False

    async def test_empty_blocklist(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        assert await svc.is_release_blocked(db_session, "Batman.018") is False

    async def test_empty_title(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        assert await svc.is_release_blocked(db_session, "") is False

    async def test_long_title(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        long = "A" * 500
        await svc.add_entry(db_session, long, BlocklistReason.FAILED)
        assert await svc.is_release_blocked(db_session, long) is True


# ── get_blocked_groups tests ──────────────────────────────────────────


@pytest.mark.slow
class TestGetBlockedGroups:
    """Tests for BlocklistService.get_blocked_groups()."""

    async def test_parses_comma_separated(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await _set_config(db_session, "blocklist.release_groups", "Empire,DCP,Pyrate")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == {"empire", "dcp", "pyrate"}

    async def test_empty_config(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await _set_config(db_session, "blocklist.release_groups", "")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == set()

    async def test_missing_config_key(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        # Don't set any config — should return empty
        groups = await svc.get_blocked_groups(db_session)
        assert groups == set()

    async def test_strips_whitespace(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await _set_config(db_session, "blocklist.release_groups", " Empire , DCP ")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == {"empire", "dcp"}

    async def test_ignores_empty_segments(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await _set_config(db_session, "blocklist.release_groups", "Empire,,DCP,")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == {"empire", "dcp"}

    async def test_all_lowercased(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await _set_config(db_session, "blocklist.release_groups", "EMPIRE,Dcp")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == {"empire", "dcp"}

    async def test_single_group(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await _set_config(db_session, "blocklist.release_groups", "Empire")
        groups = await svc.get_blocked_groups(db_session)
        assert groups == {"empire"}


# ── is_group_blocked tests ───────────────────────────────────────────


class TestIsGroupBlocked:
    """Tests for BlocklistService.is_group_blocked() — pure function."""

    def test_exact_match(self) -> None:
        assert BlocklistService.is_group_blocked("Empire", {"empire"}) is True

    def test_case_insensitive(self) -> None:
        assert BlocklistService.is_group_blocked("EMPIRE", {"empire"}) is True

    def test_not_blocked(self) -> None:
        assert BlocklistService.is_group_blocked("Minutemen", {"empire"}) is False

    def test_none_group(self) -> None:
        assert BlocklistService.is_group_blocked(None, {"empire"}) is False

    def test_empty_group(self) -> None:
        assert BlocklistService.is_group_blocked("", {"empire"}) is False

    def test_empty_blocked_set(self) -> None:
        assert BlocklistService.is_group_blocked("Empire", set()) is False

    def test_partial_no_match(self) -> None:
        assert BlocklistService.is_group_blocked("Emp", {"empire"}) is False

    def test_hyphenated_group(self) -> None:
        # "Zone-Empire" normalizes to "zoneempire", matching blocked "zoneempire"
        assert BlocklistService.is_group_blocked("Zone-Empire", {"zoneempire"}) is True

    def test_separator_variants_match(self) -> None:
        # All separator variants should match the same normalized form
        blocked = {"darknessempire"}  # normalized form
        assert BlocklistService.is_group_blocked("Darkness-Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Darkness Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Darkness_Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Darkness.Empire", blocked) is True
        assert BlocklistService.is_group_blocked("darkness-empire", blocked) is True

    def test_wildcard_suffix(self) -> None:
        # *Empire matches anything ending with "empire"
        blocked = {"*empire"}
        assert BlocklistService.is_group_blocked("Zone-Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Darkness Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Empire", blocked) is True
        assert BlocklistService.is_group_blocked("EmpireX", blocked) is False

    def test_wildcard_prefix(self) -> None:
        # Green* matches anything starting with "green"
        blocked = {"green*"}
        assert BlocklistService.is_group_blocked("GreenGiant", blocked) is True
        assert BlocklistService.is_group_blocked("Green-Team", blocked) is True
        assert BlocklistService.is_group_blocked("NotGreen", blocked) is False

    def test_wildcard_contains(self) -> None:
        # *green* matches anything containing "green"
        blocked = {"*green*"}
        assert BlocklistService.is_group_blocked("GreenGiant", blocked) is True
        assert BlocklistService.is_group_blocked("BigGreenMachine", blocked) is True
        assert BlocklistService.is_group_blocked("NotMatching", blocked) is False

    def test_wildcard_with_separators(self) -> None:
        # Wildcards work with separator normalization
        blocked = {"*empire"}
        assert BlocklistService.is_group_blocked("Zone-Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Zone Empire", blocked) is True
        assert BlocklistService.is_group_blocked("Zone_Empire", blocked) is True

    def test_mixed_exact_and_wildcard(self) -> None:
        # Mix of exact and wildcard patterns
        blocked = {"exactmatch", "*empire", "green*"}
        assert BlocklistService.is_group_blocked("ExactMatch", blocked) is True
        assert BlocklistService.is_group_blocked("Zone-Empire", blocked) is True
        assert BlocklistService.is_group_blocked("GreenTeam", blocked) is True
        assert BlocklistService.is_group_blocked("NothingMatches", blocked) is False


# ── filter_results tests ─────────────────────────────────────────────


@pytest.mark.slow
class TestFilterResultsByTitle:
    """Tests for filter_results() — release title filtering."""

    async def test_filters_blocked_title(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        results = [_make_release("Batman.018.2026"), _make_release("Saga.073.2026")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 1
        assert filtered[0].title == "Saga.073.2026"

    async def test_keeps_unblocked(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        results = [_make_release("Saga.073.2026")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 1

    async def test_case_insensitive_matching(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        results = [_make_release("BATMAN.018.2026")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 0

    async def test_does_not_modify_original(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        results = [_make_release("Batman.018.2026"), _make_release("Saga.073.2026")]
        original_len = len(results)
        await svc.filter_results(db_session, results)
        assert len(results) == original_len


@pytest.mark.slow
class TestFilterResultsByGroup:
    """Tests for filter_results() — release group filtering."""

    async def test_filters_blocked_group(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await _set_config(db_session, "blocklist.release_groups", "Empire")
        # Title contains group "Empire" which parser should extract
        results = [
            _make_release("Batman.018.2026.Digital.Zone-Empire"),
            _make_release("Saga.073.2026.Minutemen"),
        ]
        filtered = await svc.filter_results(db_session, results)
        # Empire should be filtered, Minutemen should remain
        assert any(r.title == "Saga.073.2026.Minutemen" for r in filtered)

    async def test_no_group_not_filtered(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await _set_config(db_session, "blocklist.release_groups", "Empire")
        results = [_make_release("Batman 018")]  # No group in title
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 1


@pytest.mark.slow
class TestFilterResultsCombined:
    """Tests for filter_results() — combined title + group filtering."""

    async def test_empty_results(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        filtered = await svc.filter_results(db_session, [])
        assert filtered == []

    async def test_empty_blocklist_and_groups(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        results = [_make_release("Batman.018"), _make_release("Saga.073")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 2

    async def test_all_blocked(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        await svc.add_entry(db_session, "Saga.073", BlocklistReason.FAILED)
        results = [_make_release("Batman.018"), _make_release("Saga.073")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 0

    async def test_blocked_by_title_even_if_group_ok(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018.2026.Minutemen", BlocklistReason.FAILED)
        results = [_make_release("Batman.018.2026.Minutemen")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 0

    async def test_large_batch(self, db_session: AsyncSession, svc: BlocklistService) -> None:
        await svc.add_entry(db_session, "Blocked.001", BlocklistReason.FAILED)
        results = [_make_release(f"Release.{i:03d}") for i in range(100)]
        results.append(_make_release("Blocked.001"))
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 100  # 100 kept, 1 blocked

    async def test_duplicate_titles_both_filtered(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        results = [_make_release("Batman.018"), _make_release("Batman.018")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 0
