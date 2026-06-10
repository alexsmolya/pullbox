"""Search detail diagnostics for history/log troubleshooting."""

from __future__ import annotations

from pullbox.core.release_parser import ParsedRelease
from pullbox.models.issue import IssueType
from pullbox.models.library import MatchConfidence
from pullbox.providers.base import ReleaseResult
from pullbox.services.release_validator import ValidationResult
from pullbox.services.search_service import build_search_details


def _release(title: str, *, indexer_name: str = "MyAnonamouse") -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name=indexer_name,
        download_url=f"https://example.test/{title.replace(' ', '_')}",
        size_bytes=100_000_000,
        age_days=1,
        seeders=42,
        leechers=2,
        grabs=None,
        is_torrent=True,
        category="7030",
        published_at=None,
    )


def _parsed(
    title: str,
    *,
    series_name: str | None,
    issue_number: float | None,
    year: int | None,
) -> ParsedRelease:
    return ParsedRelease(
        original_title=title,
        series_name=series_name,
        issue_number=issue_number,
        year=year,
        volume=None,
        issue_type=IssueType.ISSUE,
        scan_group="Empire",
        file_format="cbz",
        is_pack=False,
        pack_range=None,
    )


def test_search_details_include_result_explanations_for_history_and_logs() -> None:
    matched = ValidationResult(
        is_match=True,
        confidence=MatchConfidence.HIGH,
        parsed=_parsed(
            "Absolute Flash #001 (2025) (Digital) (Zone-Empire).cbz",
            series_name="Absolute Flash",
            issue_number=1.0,
            year=2025,
        ),
        release=_release("Absolute Flash #001 (2025) (Digital) (Zone-Empire).cbz"),
        series_similarity=1.0,
        match_type="exact",
        issue_match=True,
        year_match=True,
        issue_type_match=True,
    )
    rejected = ValidationResult(
        is_match=False,
        confidence=MatchConfidence.LOW,
        parsed=_parsed(
            "Absolute Flashpoint 001 (2025) (Digital).cbz",
            series_name="Absolute Flashpoint",
            issue_number=1.0,
            year=2025,
        ),
        release=_release("Absolute Flashpoint 001 (2025) (Digital).cbz", indexer_name="NZBgeek"),
        rejection_reason="Series mismatch",
        series_similarity=0.72,
        match_type="fuzzy",
        issue_match=True,
        year_match=True,
        issue_type_match=True,
    )

    details = build_search_details([matched], [rejected], search_time_ms=125, search_passes=1)

    assert details["best_match"]["reason_summary"] == "high confidence exact match"
    assert details["matched"] == [
        {
            "status": "matched",
            "title": "Absolute Flash #001 (2025) (Digital) (Zone-Empire).cbz",
            "indexer": "MyAnonamouse",
            "confidence": "high",
            "series_similarity": 1.0,
            "match_type": "exact",
            "parsed_series": "Absolute Flash",
            "parsed_issue": 1.0,
            "parsed_year": 2025,
            "issue_type": "issue",
            "rejection_reason": None,
        }
    ]
    assert details["top_rejected"] == [
        {
            "status": "rejected",
            "title": "Absolute Flashpoint 001 (2025) (Digital).cbz",
            "indexer": "NZBgeek",
            "confidence": "low",
            "reason": "Series mismatch",
            "series_similarity": 0.72,
            "match_type": "fuzzy",
            "parsed_series": "Absolute Flashpoint",
            "parsed_issue": 1.0,
            "parsed_year": 2025,
            "issue_type": "issue",
            "rejection_reason": "Series mismatch",
        }
    ]


def test_search_details_preserve_rejected_candidates_beyond_top_summary() -> None:
    rejected = [
        ValidationResult(
            is_match=False,
            confidence=MatchConfidence.LOW,
            parsed=_parsed(
                f"Absolute Flashpoint 00{index} (2025) (Digital).cbz",
                series_name="Absolute Flashpoint",
                issue_number=float(index),
                year=2025,
            ),
            release=_release(
                f"Absolute Flashpoint 00{index} (2025) (Digital).cbz",
                indexer_name="NZBgeek",
            ),
            rejection_reason=f"Series mismatch {index}",
            series_similarity=0.80 - (index * 0.01),
            match_type="fuzzy",
            issue_match=True,
            year_match=True,
            issue_type_match=True,
        )
        for index in range(1, 6)
    ]

    details = build_search_details([], rejected)

    assert len(details["top_rejected"]) == 3
    assert [item["title"] for item in details["rejected"]] == [
        "Absolute Flashpoint 001 (2025) (Digital).cbz",
        "Absolute Flashpoint 002 (2025) (Digital).cbz",
        "Absolute Flashpoint 003 (2025) (Digital).cbz",
        "Absolute Flashpoint 004 (2025) (Digital).cbz",
        "Absolute Flashpoint 005 (2025) (Digital).cbz",
    ]
    assert details["rejected_diagnostics_count"] == 5
    assert details["rejected_diagnostics_truncated"] is False


def test_search_details_identify_slow_indexers_without_disabling_them() -> None:
    query_diagnostics = [
        {
            "query": "Absolute Flash #001",
            "elapsed_ms": 1250,
            "result_count": 1,
            "indexers": [
                {
                    "indexer": "FastIndexer",
                    "elapsed_ms": 120,
                    "result_count": 0,
                    "filtered_count": 0,
                    "status": "completed",
                },
                {
                    "indexer": "SlowIndexer",
                    "elapsed_ms": 1250,
                    "result_count": 1,
                    "filtered_count": 0,
                    "status": "completed",
                },
            ],
        }
    ]

    details = build_search_details([], [], query_diagnostics=query_diagnostics)

    assert details["slow_indexers"] == [
        {
            "query": "Absolute Flash #001",
            "indexer": "SlowIndexer",
            "elapsed_ms": 1250,
            "result_count": 1,
            "filtered_count": 0,
            "status": "completed",
        }
    ]
