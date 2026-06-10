"""Tests for per-type confidence thresholds — ESM Phase 3, Task 3.1.

Covers:
- Default thresholds for each IssueType
- Custom threshold overrides via type_thresholds dict
- "never" threshold always returns False (always queue)
- Confidence ordering logic

Run:
    pytest tests/unit/test_type_thresholds.py -v
"""

from __future__ import annotations

import pytest

from pullbox.models.issue import IssueType
from pullbox.models.library import MatchConfidence
from pullbox.services.search_service import DEFAULT_TYPE_THRESHOLDS, should_auto_grab


class TestTypeThresholds:
    """Tests for should_auto_grab with per-type confidence thresholds."""

    @pytest.mark.parametrize(
        "issue_type,expected",
        [
            (IssueType.ISSUE, "medium"),
            (IssueType.ANNUAL, "high"),
            (IssueType.TPB, "high"),
            (IssueType.HC, "high"),
            (IssueType.OMNIBUS, "high"),
            (IssueType.GN, "high"),
            (IssueType.OGN, "high"),
            (IssueType.ONE_SHOT, "high"),
            (IssueType.SPECIAL, "high"),
            (IssueType.DELUXE, "high"),
            (IssueType.COMPENDIUM, "high"),
        ],
    )
    def test_default_thresholds_per_type(self, issue_type: IssueType, expected: str) -> None:
        """Each type has the correct default threshold."""
        assert DEFAULT_TYPE_THRESHOLDS[issue_type.value] == expected

    def test_issue_default_medium_auto_grabs_medium(self) -> None:
        """Standard ISSUE auto-grabs at MEDIUM confidence with defaults."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.ISSUE, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_issue_default_medium_rejects_low(self) -> None:
        """Standard ISSUE does NOT auto-grab at LOW confidence with defaults."""
        result = should_auto_grab(MatchConfidence.LOW, IssueType.ISSUE, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_tpb_default_high_grabs_high(self) -> None:
        """TPB type defaults to 'high' — HIGH confidence auto-grabs."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.TPB, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_tpb_default_high_rejects_medium(self) -> None:
        """TPB type defaults to 'high' — MEDIUM confidence is queued."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.TPB, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_hc_default_high_grabs_high(self) -> None:
        """HC type defaults to 'high' — HIGH confidence auto-grabs."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.HC, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_hc_default_high_rejects_medium(self) -> None:
        """HC type defaults to 'high' — MEDIUM confidence is queued."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.HC, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_gn_default_high_grabs_high(self) -> None:
        """GN type defaults to 'high' — HIGH confidence auto-grabs."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.GN, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_gn_default_high_rejects_medium(self) -> None:
        """GN type defaults to 'high' — MEDIUM confidence is queued."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.GN, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_ogn_default_high_grabs_high(self) -> None:
        """OGN type defaults to 'high' — HIGH confidence auto-grabs."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.OGN, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_ogn_default_high_rejects_medium(self) -> None:
        """OGN type defaults to 'high' — MEDIUM confidence is queued."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.OGN, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_deluxe_default_high_grabs_high(self) -> None:
        """DELUXE type defaults to 'high' — HIGH confidence auto-grabs."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.DELUXE, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_deluxe_default_high_rejects_medium(self) -> None:
        """DELUXE type defaults to 'high' — MEDIUM confidence is queued."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.DELUXE, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_annual_default_high_grabs_high(self) -> None:
        """ANNUAL type auto-grabs at HIGH confidence with defaults."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.ANNUAL, DEFAULT_TYPE_THRESHOLDS)
        assert result is True

    def test_annual_default_high_rejects_medium(self) -> None:
        """ANNUAL type does NOT auto-grab at MEDIUM confidence with defaults."""
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.ANNUAL, DEFAULT_TYPE_THRESHOLDS)
        assert result is False

    def test_custom_threshold_override(self) -> None:
        """Custom config overrides default thresholds."""
        custom = {**DEFAULT_TYPE_THRESHOLDS, "tpb": "medium"}
        result = should_auto_grab(MatchConfidence.MEDIUM, IssueType.TPB, custom)
        assert result is True

    def test_custom_never_override(self) -> None:
        """Custom config can set 'issue' to 'never'."""
        custom = {**DEFAULT_TYPE_THRESHOLDS, "issue": "never"}
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.ISSUE, custom)
        assert result is False

    def test_empty_thresholds_uses_fallback(self) -> None:
        """Empty thresholds dict falls back to default_threshold parameter."""
        result = should_auto_grab(
            MatchConfidence.HIGH, IssueType.ISSUE, {}, default_threshold="high"
        )
        assert result is True

        result = should_auto_grab(
            MatchConfidence.MEDIUM, IssueType.ISSUE, {}, default_threshold="high"
        )
        assert result is False

    def test_high_confidence_always_meets_medium_threshold(self) -> None:
        """HIGH confidence meets a 'medium' threshold."""
        result = should_auto_grab(MatchConfidence.HIGH, IssueType.ISSUE, {"issue": "medium"})
        assert result is True

    def test_low_confidence_never_meets_medium_threshold(self) -> None:
        """LOW confidence does not meet a 'medium' threshold."""
        result = should_auto_grab(MatchConfidence.LOW, IssueType.ISSUE, {"issue": "medium"})
        assert result is False
