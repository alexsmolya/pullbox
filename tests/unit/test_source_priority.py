"""Unit tests for source priority sorting (DCE-S.3).

Tests the _sort_by_source_priority helper function and the source_priority
SystemConfig default.

Run:
    pytest tests/unit/test_source_priority.py -v
"""

from __future__ import annotations

from pullbox.providers.base import ReleaseResult
from pullbox.services.search_service import _sort_by_source_priority


def _make_result(title: str, is_torrent: bool) -> ReleaseResult:
    """Create a minimal ReleaseResult for sorting tests."""
    return ReleaseResult(
        title=title,
        indexer_name="test",
        download_url=f"http://example.com/{title}",
        size_bytes=100,
        age_days=1,
        seeders=10 if is_torrent else None,
        leechers=5 if is_torrent else None,
        grabs=50 if not is_torrent else None,
        is_torrent=is_torrent,
        category="comics",
        published_at=None,
    )


class TestSortBySourcePriority:
    """Tests for _sort_by_source_priority()."""

    def test_usenet_first_default(self) -> None:
        """Default priority ["usenet", "torrent"] puts NZBs first."""
        results = [
            _make_result("torrent1", is_torrent=True),
            _make_result("nzb1", is_torrent=False),
            _make_result("torrent2", is_torrent=True),
            _make_result("nzb2", is_torrent=False),
            _make_result("nzb3", is_torrent=False),
        ]
        sorted_results = _sort_by_source_priority(results, ["usenet", "torrent"])

        # First 3 should be NZBs, last 2 should be torrents
        assert not sorted_results[0].is_torrent
        assert not sorted_results[1].is_torrent
        assert not sorted_results[2].is_torrent
        assert sorted_results[3].is_torrent
        assert sorted_results[4].is_torrent

    def test_torrent_first(self) -> None:
        """Priority ["torrent", "usenet"] puts torrents first."""
        results = [
            _make_result("nzb1", is_torrent=False),
            _make_result("torrent1", is_torrent=True),
            _make_result("nzb2", is_torrent=False),
        ]
        sorted_results = _sort_by_source_priority(results, ["torrent", "usenet"])

        assert sorted_results[0].is_torrent
        assert not sorted_results[1].is_torrent
        assert not sorted_results[2].is_torrent

    def test_stable_sort_preserves_intra_protocol_order(self) -> None:
        """Within the same protocol, original order is preserved."""
        results = [
            _make_result("nzb_A", is_torrent=False),
            _make_result("nzb_B", is_torrent=False),
            _make_result("nzb_C", is_torrent=False),
        ]
        sorted_results = _sort_by_source_priority(results, ["usenet", "torrent"])

        assert sorted_results[0].title == "nzb_A"
        assert sorted_results[1].title == "nzb_B"
        assert sorted_results[2].title == "nzb_C"

    def test_all_nzb_with_torrent_first_still_returns_all(self) -> None:
        """All-NZB results with torrent-first priority still returned."""
        results = [_make_result("nzb1", False), _make_result("nzb2", False)]
        sorted_results = _sort_by_source_priority(results, ["torrent", "usenet"])

        assert len(sorted_results) == 2

    def test_all_torrent_with_usenet_first_still_returns_all(self) -> None:
        """All-torrent results with usenet-first priority still returned."""
        results = [_make_result("t1", True), _make_result("t2", True)]
        sorted_results = _sort_by_source_priority(results, ["usenet", "torrent"])

        assert len(sorted_results) == 2

    def test_empty_results(self) -> None:
        """Empty results → empty list, no crash."""
        assert _sort_by_source_priority([], ["usenet", "torrent"]) == []

    def test_single_element_priority_list(self) -> None:
        """Single-element priority still sorts correctly."""
        results = [
            _make_result("t1", True),
            _make_result("n1", False),
        ]
        sorted_results = _sort_by_source_priority(results, ["torrent"])

        # Torrent first, usenet sinks to bottom (unknown protocol rank)
        assert sorted_results[0].is_torrent

    def test_unknown_protocol_sinks_to_bottom(self) -> None:
        """Results from unknown protocols go after known ones."""
        results = [
            _make_result("t1", True),
            _make_result("n1", False),
        ]
        # Only "usenet" in priority — torrent is "unknown" and sinks
        sorted_results = _sort_by_source_priority(results, ["usenet"])

        assert not sorted_results[0].is_torrent  # usenet first
        assert sorted_results[1].is_torrent  # torrent sinks

    def test_future_ddl_in_priority_no_effect(self) -> None:
        """["usenet", "torrent", "ddl"] — ddl has no matching results, no crash."""
        results = [
            _make_result("t1", True),
            _make_result("n1", False),
        ]
        sorted_results = _sort_by_source_priority(
            results,
            ["usenet", "torrent", "ddl"],
        )

        assert not sorted_results[0].is_torrent
        assert sorted_results[1].is_torrent

    def test_same_protocol_is_noop(self) -> None:
        """All results same protocol → order unchanged."""
        results = [
            _make_result("a", True),
            _make_result("b", True),
            _make_result("c", True),
        ]
        sorted_results = _sort_by_source_priority(results, ["usenet", "torrent"])

        assert [r.title for r in sorted_results] == ["a", "b", "c"]
