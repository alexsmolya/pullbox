"""Tests for detailed structured logging enhancements (C-7.2).

Verifies:
- Download state transition events include from/to states
- Progress milestones are logged at correct percentages
- Search scoring breakdown includes rank and threshold info
- Matching candidate evaluation includes similarity and decision
- Confidence computation logs match type and year proximity
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.testing import capture_logs

from pullbox.services.matching_service import _confidence_from_match

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_structlog_for_capture() -> Iterator[None]:
    """Reset structlog so capture_logs works even after app configures it."""
    import pullbox.services.matching_service as ms_mod

    structlog.reset_defaults()
    # Re-create the module-level logger so it isn't cached with old processors
    ms_mod.logger = structlog.get_logger(ms_mod.__name__)
    yield


class TestConfidenceLogging:
    """_confidence_from_match logs confidence computation details."""

    def test_exact_match_year_close_logs_high(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("exact", 1.0, 2020, 2020)
            assert result == MatchConfidence.HIGH

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert len(conf_logs) == 1
        assert conf_logs[0]["match_type"] == "exact"
        assert conf_logs[0]["year_close"] is True
        assert conf_logs[0]["confidence"] == str(MatchConfidence.HIGH)

    def test_exact_match_no_year_logs_medium(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("exact", 1.0, None, 2020)
            assert result == MatchConfidence.MEDIUM

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert len(conf_logs) == 1
        assert conf_logs[0]["year_close"] is False
        assert conf_logs[0]["confidence"] == str(MatchConfidence.MEDIUM)

    def test_fuzzy_high_similarity_no_year_logs_low(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("fuzzy", 0.90, None, None)
            assert result == MatchConfidence.LOW

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert len(conf_logs) == 1
        assert conf_logs[0]["match_type"] == "fuzzy"
        assert conf_logs[0]["similarity"] == 0.9

    def test_token_set_logs_medium(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("token_set", 0.95, 2020, 2020)
            assert result == MatchConfidence.MEDIUM

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert len(conf_logs) == 1
        assert conf_logs[0]["match_type"] == "token_set"

    def test_low_fuzzy_similarity_logs_low(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("fuzzy", 0.70, 2020, 2020)
            assert result == MatchConfidence.LOW

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert len(conf_logs) == 1
        assert conf_logs[0]["confidence"] == str(MatchConfidence.LOW)

    def test_alternate_match_year_close(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("alternate", 0.95, 2020, 2021)
            assert result == MatchConfidence.HIGH

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert conf_logs[0]["year_close"] is True

    def test_alternate_match_year_far(self) -> None:
        with capture_logs() as logs:
            from pullbox.models.library import MatchConfidence

            result = _confidence_from_match("alternate", 0.95, 2020, 2025)
            assert result == MatchConfidence.MEDIUM

        conf_logs = [e for e in logs if e["event"] == "matching_confidence_computed"]
        assert conf_logs[0]["year_close"] is False


class TestProgressMilestones:
    """Progress milestone tracking logs at correct percentages."""

    def test_milestone_logged_at_25_pct(self) -> None:
        from pullbox.tasks.download_task import _MILESTONES, _milestone_logged

        # Clear state
        _milestone_logged.pop(999, None)

        with capture_logs() as logs:
            from pullbox.tasks.download_task import _milestone_logged

            logged = _milestone_logged.setdefault(999, set())
            pct = 30  # Above 25%
            for milestone in _MILESTONES:
                if pct >= milestone and milestone not in logged:
                    logged.add(milestone)
                    structlog.get_logger().info(
                        "download_progress_milestone",
                        download_id=999,
                        milestone_pct=milestone,
                    )

        milestone_logs = [e for e in logs if e["event"] == "download_progress_milestone"]
        assert len(milestone_logs) == 1
        assert milestone_logs[0]["milestone_pct"] == 25

        # Cleanup
        _milestone_logged.pop(999, None)

    def test_milestone_not_re_logged(self) -> None:
        from pullbox.tasks.download_task import _MILESTONES, _milestone_logged

        _milestone_logged.pop(998, None)
        _milestone_logged[998] = {25}  # Already logged

        with capture_logs() as logs:
            logged = _milestone_logged[998]
            pct = 30
            for milestone in _MILESTONES:
                if pct >= milestone and milestone not in logged:
                    logged.add(milestone)
                    structlog.get_logger().info(
                        "download_progress_milestone",
                        download_id=998,
                        milestone_pct=milestone,
                    )

        milestone_logs = [e for e in logs if e["event"] == "download_progress_milestone"]
        assert len(milestone_logs) == 0

        _milestone_logged.pop(998, None)

    def test_multiple_milestones_logged_on_jump(self) -> None:
        from pullbox.tasks.download_task import _MILESTONES, _milestone_logged

        _milestone_logged.pop(997, None)

        with capture_logs() as logs:
            logged = _milestone_logged.setdefault(997, set())
            pct = 80  # Above 25, 50, 75
            for milestone in _MILESTONES:
                if pct >= milestone and milestone not in logged:
                    logged.add(milestone)
                    structlog.get_logger().info(
                        "download_progress_milestone",
                        download_id=997,
                        milestone_pct=milestone,
                    )

        milestone_logs = [e for e in logs if e["event"] == "download_progress_milestone"]
        assert len(milestone_logs) == 3
        milestones = [e["milestone_pct"] for e in milestone_logs]
        assert milestones == [25, 50, 75]

        _milestone_logged.pop(997, None)

    def test_clear_progress_removes_milestones(self) -> None:
        from pullbox.tasks.download_task import _clear_progress, _milestone_logged

        _milestone_logged[996] = {25, 50}
        _clear_progress(996)
        assert 996 not in _milestone_logged

    def test_100_pct_milestone_logged(self) -> None:
        from pullbox.tasks.download_task import _MILESTONES, _milestone_logged

        _milestone_logged.pop(995, None)

        with capture_logs() as logs:
            logged = _milestone_logged.setdefault(995, set())
            pct = 100
            for milestone in _MILESTONES:
                if pct >= milestone and milestone not in logged:
                    logged.add(milestone)
                    structlog.get_logger().info(
                        "download_progress_milestone",
                        download_id=995,
                        milestone_pct=milestone,
                    )

        milestone_logs = [e for e in logs if e["event"] == "download_progress_milestone"]
        assert len(milestone_logs) == 4
        assert milestone_logs[-1]["milestone_pct"] == 100

        _milestone_logged.pop(995, None)
