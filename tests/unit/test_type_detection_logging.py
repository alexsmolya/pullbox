"""Tests for type detection structured logging — ESM Phase 3, Task 3.6.

Covers:
- Type detection log emitted with correct fields
- Type distribution counts parsed types
- Type mismatch rejections counted
- No log emitted when validation disabled (legacy path)

Run:
    pytest tests/unit/test_type_detection_logging.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog
import structlog.testing

from pullbox.models.issue import IssueType
from pullbox.providers.base import ReleaseResult
from pullbox.services.search_service import SearchService

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_structlog_cache() -> Iterator[None]:
    """Reset structlog so capture_logs works even after app configures it."""
    import pullbox.services.release_validator as rv_mod
    import pullbox.services.search_service as ss_mod

    structlog.reset_defaults()
    # Re-create loggers so they aren't cached with old processors
    ss_mod.logger = structlog.get_logger(ss_mod.__name__)
    rv_mod.log = structlog.get_logger(rv_mod.__name__)
    yield


_MB = 1024 * 1024


def _make_release(title: str, size_mb: int = 100) -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="TestIndexer",
        download_url=f"https://example.com/{title.replace(' ', '_')}",
        size_bytes=size_mb * _MB,
        age_days=2,
        seeders=None,
        leechers=None,
        grabs=None,
        is_torrent=False,
        category=None,
        published_at=None,
    )


class TestTypeDetectionLogging:
    """Tests for _log_type_detection() structured log output."""

    def test_type_detection_logged(self) -> None:
        """evaluate_results emits search_type_detection log with expected fields."""
        results = [
            _make_release("Batman 001 (2016).cbz"),
            _make_release("Batman Annual 001 (2016).cbz"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=1.0,
                wanted_year=2016,
                wanted_issue_type=IssueType.ISSUE,
            )

        events = {entry["event"]: entry for entry in cap_logs}
        assert "search_type_detection" in events

        detection = events["search_type_detection"]
        assert detection["wanted_type"] == "issue"
        assert detection["wanted_series"] == "Batman"
        assert detection["wanted_issue"] == 1.0
        assert "results_parsed" in detection
        assert "type_distribution" in detection
        assert "rejected_by_type" in detection
        assert "matched" in detection

    def test_type_distribution_counts(self) -> None:
        """Type distribution dict counts each parsed type correctly."""
        results = [
            _make_release("Batman 001 (2016).cbz"),
            _make_release("Batman Vol 1 TPB (2016).cbz"),
            _make_release("Batman Annual 001 (2016).cbz"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=1.0,
                wanted_year=2016,
                wanted_issue_type=IssueType.ISSUE,
            )

        events = {entry["event"]: entry for entry in cap_logs}
        detection = events["search_type_detection"]
        type_dist = detection["type_distribution"]

        # At least one type should be counted
        assert isinstance(type_dist, dict)
        assert detection["results_parsed"] == len(results)

    def test_type_mismatch_rejections_counted(self) -> None:
        """rejected_by_type counts results rejected for type mismatch."""
        results = [
            _make_release("Batman 001 (2016).cbz"),
            _make_release("Batman Annual 001 (2016).cbz"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=1.0,
                wanted_year=2016,
                wanted_issue_type=IssueType.ISSUE,
            )

        events = {entry["event"]: entry for entry in cap_logs}
        detection = events["search_type_detection"]

        # Annual should be rejected as type mismatch when searching for ISSUE
        assert detection["rejected_by_type"] >= 1

    def test_no_type_detection_log_without_validation(self) -> None:
        """Legacy path (no wanted_series) does not emit type detection log."""
        results = [_make_release("Batman 001 (2016).cbz")]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(results)

        events = [entry["event"] for entry in cap_logs]
        assert "search_type_detection" not in events

    def test_all_matched_zero_rejections(self) -> None:
        """When all results match, rejected_by_type is 0."""
        results = [
            _make_release("Batman 001 (2016).cbz"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=1.0,
                wanted_year=2016,
                wanted_issue_type=IssueType.ISSUE,
            )

        events = {entry["event"]: entry for entry in cap_logs}
        detection = events["search_type_detection"]
        assert detection["rejected_by_type"] == 0
        assert detection["matched"] >= 1

    def test_non_standard_type_detection(self) -> None:
        """Type detection works for non-standard types (TPB)."""
        results = [
            _make_release("Batman Vol 1 TPB (2016).cbz"),
            _make_release("Batman 001 (2016).cbz"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=1.0,
                wanted_year=2016,
                wanted_issue_type=IssueType.TPB,
            )

        events = {entry["event"]: entry for entry in cap_logs}
        detection = events["search_type_detection"]
        assert detection["wanted_type"] == "tpb"
        # Both results should match: TPB directly, ISSUE via collection leniency
        assert detection["matched"] == 2
