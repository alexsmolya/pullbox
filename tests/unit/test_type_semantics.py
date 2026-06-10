"""Unit tests for shared issue/series type semantics."""

from __future__ import annotations

from pullbox.core.type_semantics import (
    TypeFamily,
    canonical_issue_type_for_series_type,
    canonical_series_type_for_issue_type,
    issue_type_compatibility,
    issue_type_family,
    series_type_family,
)
from pullbox.models.issue import IssueType
from pullbox.models.series import SeriesType
from pullbox.services.semantic_matching import ImportPolicy, SearchPolicy


class TestTypeFamilies:
    """Type families should classify all current issue and series types."""

    def test_issue_like_family(self) -> None:
        assert issue_type_family(IssueType.ISSUE) == TypeFamily.STANDARD
        assert issue_type_family(IssueType.ANNUAL) == TypeFamily.ISSUE_LIKE
        assert issue_type_family(IssueType.ONE_SHOT) == TypeFamily.ISSUE_LIKE
        assert issue_type_family(IssueType.SPECIAL) == TypeFamily.ISSUE_LIKE

    def test_collection_family(self) -> None:
        for issue_type in (
            IssueType.TPB,
            IssueType.HC,
            IssueType.DELUXE,
            IssueType.GN,
            IssueType.OGN,
            IssueType.OMNIBUS,
            IssueType.COMPENDIUM,
            IssueType.VOLUME,
        ):
            assert issue_type_family(issue_type) == TypeFamily.COLLECTION

    def test_series_families(self) -> None:
        assert series_type_family(SeriesType.STANDARD) == TypeFamily.STANDARD
        assert series_type_family(SeriesType.ANNUAL) == TypeFamily.ISSUE_LIKE
        assert series_type_family(SeriesType.ONE_SHOT) == TypeFamily.ISSUE_LIKE
        assert series_type_family(SeriesType.SPECIAL) == TypeFamily.ISSUE_LIKE
        for series_type in (
            SeriesType.TPB,
            SeriesType.HARDCOVER,
            SeriesType.DELUXE,
            SeriesType.GRAPHIC_NOVEL,
            SeriesType.OMNIBUS,
            SeriesType.COMPENDIUM,
            SeriesType.VOLUME,
        ):
            assert series_type_family(series_type) == TypeFamily.COLLECTION


class TestCanonicalMappings:
    """Issue/series mapping should be explicit and reversible where intended."""

    def test_issue_to_series_mapping(self) -> None:
        assert canonical_series_type_for_issue_type(IssueType.TPB) == SeriesType.TPB
        assert canonical_series_type_for_issue_type(IssueType.HC) == SeriesType.HARDCOVER
        assert canonical_series_type_for_issue_type(IssueType.DELUXE) == SeriesType.DELUXE
        assert canonical_series_type_for_issue_type(IssueType.GN) == SeriesType.GRAPHIC_NOVEL
        assert canonical_series_type_for_issue_type(IssueType.OGN) == SeriesType.GRAPHIC_NOVEL
        assert canonical_series_type_for_issue_type(IssueType.VOLUME) == SeriesType.VOLUME

    def test_series_to_issue_mapping(self) -> None:
        assert canonical_issue_type_for_series_type(SeriesType.TPB) == IssueType.TPB
        assert canonical_issue_type_for_series_type(SeriesType.HARDCOVER) == IssueType.HC
        assert canonical_issue_type_for_series_type(SeriesType.GRAPHIC_NOVEL) == IssueType.GN
        assert canonical_issue_type_for_series_type(SeriesType.VOLUME) == IssueType.VOLUME


class TestIssueTypeCompatibility:
    """Compatibility should vary by family and policy strictness."""

    def test_issue_like_types_do_not_silently_become_collections(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.ANNUAL,
            wanted_type=IssueType.TPB,
            policy=SearchPolicy(),
        )
        assert compatibility.compatible is False

    def test_search_policy_allows_collection_family_matching(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.HC,
            wanted_type=IssueType.DELUXE,
            policy=SearchPolicy(),
        )
        assert compatibility.compatible is True
        assert compatibility.lowers_confidence is True

    def test_import_policy_keeps_collection_family_compatible_but_strict(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.GN,
            wanted_type=IssueType.TPB,
            policy=ImportPolicy(),
        )
        assert compatibility.compatible is True
        assert compatibility.lowers_confidence is True
        assert compatibility.allow_issue_number_fallback is False

    def test_search_policy_rejects_collection_to_standard_issue_fallback(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.TPB,
            wanted_type=IssueType.ISSUE,
            policy=SearchPolicy(),
        )
        assert compatibility.compatible is False

    def test_import_policy_rejects_collection_to_standard_issue_fallback(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.TPB,
            wanted_type=IssueType.ISSUE,
            policy=ImportPolicy(),
        )
        assert compatibility.compatible is False

    def test_search_policy_can_infer_collection_target_from_plain_release(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.ISSUE,
            wanted_type=IssueType.TPB,
            policy=SearchPolicy(),
        )
        assert compatibility.compatible is True
        assert compatibility.prefer_subtitle is True

    def test_one_shot_remains_issue_like(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.ONE_SHOT,
            wanted_type=IssueType.ISSUE,
            policy=ImportPolicy(),
        )
        assert compatibility.compatible is True
        assert compatibility.prefer_volume_number is False

    def test_annual_does_not_fallback_to_standard_issue(self) -> None:
        compatibility = issue_type_compatibility(
            parsed_type=IssueType.ANNUAL,
            wanted_type=IssueType.ISSUE,
            policy=SearchPolicy(),
        )
        assert compatibility.compatible is False
