"""Unit tests for the shared semantic match engine."""

from __future__ import annotations

from pullbox.core.source_metadata import MetadataSignal, SourceMetadataExtractor
from pullbox.models.issue import IssueType
from pullbox.providers.base import SeriesSearchResult
from pullbox.services.semantic_matching import (
    ImportPolicy,
    SearchPolicy,
    SemanticMatchConfig,
    SemanticMatchEngine,
)


class TestSemanticMatchEngine:
    """Search and import should share semantics with different strictness."""

    def setup_method(self) -> None:
        self.extractor = SourceMetadataExtractor()
        self.config = SemanticMatchConfig()

    def test_collection_release_matches_collection_target(self) -> None:
        metadata = self.extractor.from_release_title("Batman TPB Vol 5 [2024] [Digital]")
        decision = SemanticMatchEngine(self.config, SearchPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.TPB,
        )

        assert decision.is_match is True
        assert decision.match_diagnostics["type_mode"] == "exact"

    def test_volume_subtitle_issue_match_requires_issue_title_corroboration(self) -> None:
        metadata = self.extractor.from_release_title("Fearscape.Vol.02.A.Dark.Interlude.2023.pdf")
        metadata = metadata.model_copy(
            update={
                "series_name": "Fearscape",
                "issue_number": 2.0,
                "diagnostics": {
                    "volume_subtitle_hint": {
                        "base_series": "Fearscape",
                        "subtitle": "A Dark Interlude",
                        "issue_number": 2.0,
                    }
                },
            }
        )

        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Fearscape",
            wanted_issue=2.0,
            wanted_year=2019,
            wanted_issue_type=IssueType.VOLUME,
            wanted_issue_cv_id=1030016,
            wanted_issue_title="Vol. 2: A Dark Interlude",
        )

        assert decision.is_match is True
        assert decision.match_method == "issue_number"

    def test_volume_subtitle_issue_match_rejects_wrong_issue_title(self) -> None:
        metadata = self.extractor.from_release_title("Dead Space V02 Salvage.pdf")
        metadata = metadata.model_copy(
            update={
                "series_name": "Dead Space",
                "issue_number": 2.0,
                "diagnostics": {
                    "volume_subtitle_hint": {
                        "base_series": "Dead Space",
                        "subtitle": "Salvage",
                        "issue_number": 2.0,
                    }
                },
            }
        )

        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Dead Space",
            wanted_issue=2.0,
            wanted_year=2008,
            wanted_issue_type=IssueType.VOLUME,
            wanted_issue_cv_id=123456,
            wanted_issue_title="Part Two",
        )

        assert decision.is_match is False
        assert decision.match_method == "issue_title_mismatch"

    def test_volume_subtitle_issue_match_accepts_series_title_corroboration(self) -> None:
        metadata = self.extractor.from_release_title(
            "The United States of Murder Inc. v01 - Truth (2015).cbz"
        )

        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="The United States of Murder Inc.: Truth",
            wanted_issue=1.0,
            wanted_year=2015,
            wanted_issue_type=IssueType.VOLUME,
            wanted_issue_cv_id=483095,
            wanted_issue_title="Volume 1",
        )

        assert decision.is_match is True
        assert decision.match_method == "issue_number"

    def test_import_policy_rejects_same_collection_tagged_issue_candidate(self) -> None:
        metadata = self.extractor.from_release_title("Batman TPB Vol 5 [2024] [Digital]")
        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
        )

        assert decision.is_match is False
        assert "Issue type mismatch" in (decision.rejection_reason or "")

    def test_search_policy_accepts_collection_subtitle_without_number(self) -> None:
        metadata = self.extractor.from_release_title(
            "Immortal Thor All Weather Turns To Storm [2024] [Digital]"
        )
        decision = SemanticMatchEngine(self.config, SearchPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Immortal Thor",
            wanted_issue=1.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.TPB,
        )

        assert decision.is_match is True
        assert decision.match_diagnostics["issue_check_skipped"] is True

    def test_search_policy_rejects_part_title_as_implicit_issue_one(self) -> None:
        metadata = self.extractor.from_release_title(
            "Absolute Flash: The Trials of the Flash: Iron Heights, "
            "Part 1 by Jeff Lemire [ENG / CBZ]"
        )
        decision = SemanticMatchEngine(self.config, SearchPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Absolute Flash",
            wanted_issue=1.0,
            wanted_year=2025,
            wanted_issue_type=IssueType.ISSUE,
        )

        assert decision.is_match is False
        assert "Issue mismatch" in (decision.rejection_reason or "")

    def test_import_policy_accepts_special_without_explicit_issue_one(self) -> None:
        metadata = self.extractor.from_release_title("Flash Gordon - The 1995 Special (2026).cbr")
        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Flash Gordon - The 1995 Special",
            wanted_issue=1.0,
            wanted_year=2026,
            wanted_issue_type=IssueType.SPECIAL,
        )

        assert decision.is_match is True
        assert decision.match_method == "implicit_issue_one"

    def test_import_policy_accepts_annual_without_explicit_issue_one(self) -> None:
        metadata = self.extractor.from_release_title(
            "Street Sharks - Annual 2026 (2026) (Digital) (Pyrate-DCP).cbz"
        )
        metadata = metadata.model_copy(update={"series_name": "Street Sharks: Annual 2026"})

        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Street Sharks: Annual 2026",
            wanted_issue=1.0,
            wanted_year=2026,
            wanted_issue_type=IssueType.ANNUAL,
        )

        assert decision.is_match is True
        assert decision.match_method == "implicit_issue_one"

    def test_wrong_issue_number_never_matches(self) -> None:
        metadata = self.extractor.from_release_title("Batman 050 [2024] [Digital]")
        decision = SemanticMatchEngine(self.config, SearchPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
        )

        assert decision.is_match is False
        assert "Issue mismatch" in (decision.rejection_reason or "")

    def test_explicit_provider_issue_id_beats_parsed_issue_number(self) -> None:
        metadata = self.extractor.from_release_title("Batman 045 [2024] [Digital]")
        metadata = metadata.model_copy(
            update={
                "comicvine_issue_id": 987654,
                "signals": {
                    **metadata.signals,
                    "comicvine_issue_id": "comicinfo",
                },
            }
        )
        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Batman",
            wanted_issue=12.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
            wanted_issue_cv_id=987654,
        )

        assert decision.is_match is True
        assert decision.match_method == "comicvine_issue_id"

    def test_strong_comicvine_issue_id_mismatch_rejects_issue_number_fallback(self) -> None:
        metadata = self.extractor.from_release_title("Absolute Martian Manhunter (2025) Vol 01.cbz")
        metadata = metadata.model_copy(
            update={
                "series_name": "Absolute Martian Manhunter",
                "year": 2025,
                "comicvine_issue_id": 1144216,
                "signals": {
                    **metadata.signals,
                    "comicvine_issue_id": MetadataSignal.COMICINFO,
                },
            }
        )

        decision = SemanticMatchEngine(self.config, ImportPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Absolute Martian Manhunter",
            wanted_issue=1.0,
            wanted_year=2025,
            wanted_issue_type=IssueType.VOLUME,
            wanted_issue_cv_id=1100110,
        )

        assert decision.is_match is False
        assert decision.match_method == "comicvine_issue_id_mismatch"
        assert "ComicVine issue ID mismatch" in (decision.rejection_reason or "")

    def test_collection_family_match_lowers_confidence(self) -> None:
        metadata = self.extractor.from_release_title("Cairo Hardcover (2007) (Digital)")
        decision = SemanticMatchEngine(self.config, SearchPolicy()).match_against_issue(
            metadata=metadata,
            wanted_series="Cairo",
            wanted_issue=1.0,
            wanted_year=2007,
            wanted_issue_type=IssueType.DELUXE,
        )

        assert decision.is_match is True
        assert decision.lowers_confidence is True

    def test_collection_source_prefers_single_ended_series_shape(self) -> None:
        metadata = self.extractor.from_release_title("Absolute Martian Manhunter TPB Vol 1 (2025)")
        engine = SemanticMatchEngine(self.config, ImportPolicy())
        collection_candidate = SeriesSearchResult(
            provider_id="168590",
            title="Absolute Martian Manhunter",
            year_start=2025,
            publisher="DC Comics",
            issue_count=1,
            status="Ended",
            cover_url=None,
            description=None,
        )
        serial_candidate = SeriesSearchResult(
            provider_id="162966",
            title="Absolute Martian Manhunter",
            year_start=2025,
            publisher="DC Comics",
            issue_count=10,
            status="Continuing",
            cover_url=None,
            description=None,
        )

        collection_score = engine.score_series_search_result(
            metadata=metadata,
            candidate=collection_candidate,
        )
        serial_score = engine.score_series_search_result(
            metadata=metadata,
            candidate=serial_candidate,
        )

        assert (
            collection_score.diagnostics["shape_adjustment"]
            > serial_score.diagnostics["shape_adjustment"]
        )

    def test_standard_source_penalizes_single_release_series_shape(self) -> None:
        metadata = self.extractor.from_release_title("Absolute Martian Manhunter 002 (2025)")
        engine = SemanticMatchEngine(self.config, ImportPolicy())
        collection_candidate = SeriesSearchResult(
            provider_id="168590",
            title="Absolute Martian Manhunter",
            year_start=2025,
            publisher="DC Comics",
            issue_count=1,
            status="Ended",
            cover_url=None,
            description=None,
        )
        serial_candidate = SeriesSearchResult(
            provider_id="162966",
            title="Absolute Martian Manhunter",
            year_start=2025,
            publisher="DC Comics",
            issue_count=10,
            status="Continuing",
            cover_url=None,
            description=None,
        )

        collection_score = engine.score_series_search_result(
            metadata=metadata,
            candidate=collection_candidate,
        )
        serial_score = engine.score_series_search_result(
            metadata=metadata,
            candidate=serial_candidate,
        )

        assert serial_score.score > collection_score.score
