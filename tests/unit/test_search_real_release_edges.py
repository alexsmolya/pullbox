"""Fixture-backed search edge cases for real-world release titles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pullbox.models.issue import IssueType
from pullbox.models.library import MatchConfidence
from pullbox.providers.base import ReleaseResult
from pullbox.services.release_validator import ReleaseValidator
from pullbox.services.search_query_helpers import _is_comic_category
from pullbox.services.search_scoring import _score_language
from pullbox.services.search_service import build_search_details, score_release

_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"


def _release_from_nzbgeek(row: dict[str, object]) -> ReleaseResult:
    title = str(row["title"])
    return ReleaseResult(
        title=title,
        indexer_name="NZBgeek",
        download_url=str(row.get("guid") or f"https://example.test/{title.replace(' ', '_')}"),
        size_bytes=int(row["size"]) if row.get("size") is not None else None,
        age_days=None,
        seeders=None,
        leechers=None,
        grabs=int(row["grabs"]) if row.get("grabs") is not None else None,
        is_torrent=False,
        category=str(row.get("category") or ""),
        published_at=None,
    )


def _release_from_prowlarr(row: dict[str, object]) -> ReleaseResult:
    title = str(row["title"])
    category_ids = row.get("category_ids")
    category = (
        ",".join(str(category_id) for category_id in category_ids)
        if isinstance(category_ids, list)
        else None
    )
    return ReleaseResult(
        title=title,
        indexer_name=str(row.get("indexer") or "Prowlarr"),
        download_url=str(row.get("guid") or f"https://example.test/{title.replace(' ', '_')}"),
        size_bytes=int(row["size"]) if row.get("size") is not None else None,
        age_days=int(row["age_days"]) if row.get("age_days") is not None else None,
        seeders=int(row["seeders"]) if row.get("seeders") is not None else None,
        leechers=int(row["leechers"]) if row.get("leechers") is not None else None,
        grabs=int(row["grabs"]) if row.get("grabs") is not None else None,
        is_torrent=row.get("protocol") == "torrent",
        category=category,
        published_at=None,
    )


def _absolute_wonder_woman_019(rows: list[dict[str, object]]) -> dict[str, object]:
    for row in rows:
        if "Absolute Wonder Woman 019" in str(row.get("title", "")):
            return row
    pytest.fail("Absolute Wonder Woman 019 fixture record is missing")


def _find_fixture_row(rows: list[dict[str, object]], needle: str) -> dict[str, object]:
    for row in rows:
        if needle.lower() in str(row.get("title", "")).lower():
            return row
    pytest.fail(f"{needle!r} fixture record is missing")


def _prowlarr_non_issue_results() -> list[dict[str, object]]:
    raw = json.loads((_FIXTURE_DIR / "prowlarr_test_fixtures.json").read_text())
    rows = raw["non_issue_results"]
    assert isinstance(rows, list)
    return rows


def _assert_matches(
    release: ReleaseResult,
    *,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int | None,
    wanted_type: IssueType,
) -> None:
    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_issue_type=wanted_type,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].parsed.issue_type == wanted_type


def _assert_rejects(
    release: ReleaseResult,
    *,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int | None,
    wanted_type: IssueType,
    reason_contains: str,
) -> None:
    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_issue_type=wanted_type,
    )

    assert matched == []
    assert len(rejected) == 1
    assert rejected[0].rejection_reason is not None
    assert reason_contains in rejected[0].rejection_reason


@pytest.mark.parametrize(
    "title",
    [
        "Absolute Flash 1 (2025) (Digital) (Zone-Empire).cbz",
        "Absolute Flash 01 (2025) (Digital) (Zone-Empire).cbz",
        "Absolute Flash #01 (2025) (Digital) (Zone-Empire).cbz",
        "Absolute Flash 001 (2025) (Digital) (Zone-Empire).cbz",
        "Absolute Flash #001 (2025) (Digital) (Zone-Empire).cbz",
    ],
)
def test_absolute_flash_strict_issue_tokens_match(title: str) -> None:
    release = ReleaseResult(
        title=title,
        indexer_name="MyAnonamouse",
        download_url="https://example.test/absolute-flash-1",
        size_bytes=100_000_000,
        age_days=1,
        seeders=42,
        leechers=2,
        grabs=None,
        is_torrent=True,
        category="7030",
        published_at=None,
    )

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Absolute Flash",
        wanted_issue=1.0,
        wanted_year=2025,
        wanted_issue_type=IssueType.ISSUE,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].confidence.value == "high"
    assert matched[0].parsed.series_name == "Absolute Flash"
    assert matched[0].parsed.issue_number == 1.0


def test_absolute_wonder_woman_019_matches_from_nzbgeek_fixture(
    nzbgeek_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_nzbgeek(_absolute_wonder_woman_019(nzbgeek_issue_results))

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Absolute Wonder Woman",
        wanted_issue=19.0,
        wanted_year=2025,
        wanted_issue_type=IssueType.ISSUE,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].confidence.value == "high"
    assert matched[0].parsed.issue_number == 19.0


@pytest.mark.parametrize(
    ("needle", "wanted_series", "wanted_issue", "wanted_year", "wanted_type"),
    [
        ("Invincible Vol. 9", "Invincible", 9.0, 2008, IssueType.TPB),
        ("Batman Annual 005", "Batman", 5.0, 1963, IssueType.ANNUAL),
        ("Gargoyles x Fantastic Four", "Gargoyles x Fantastic Four", 1.0, 2025, IssueType.ONE_SHOT),
    ],
)
def test_real_fixture_special_issue_types_match(
    nzbgeek_issue_results: list[dict[str, object]],
    needle: str,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int,
    wanted_type: IssueType,
) -> None:
    release = _release_from_nzbgeek(_find_fixture_row(nzbgeek_issue_results, needle))

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_issue_type=wanted_type,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].parsed.issue_type == wanted_type
    assert score_release(release) > 0


def test_real_fixture_pack_rejection_remains_visible_in_search_details(
    nzbgeek_non_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_nzbgeek(
        _find_fixture_row(nzbgeek_non_issue_results, "Black Science 001-043")
    )

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Black Science",
        wanted_issue=1.0,
        wanted_year=2013,
        wanted_issue_type=IssueType.ISSUE,
    )
    details = build_search_details(matched, rejected)

    assert matched == []
    assert len(rejected) == 1
    assert rejected[0].parsed.is_pack is True
    assert "Multi-issue pack" in (rejected[0].rejection_reason or "")
    assert details["rejected"][0]["title"] == release.title
    assert details["top_rejected"][0]["reason"] == rejected[0].rejection_reason


def test_noisy_torrent_false_positive_rejects_with_visible_reason(
    prowlarr_torrent_results: list[dict[str, object]],
) -> None:
    release = _release_from_prowlarr(
        _find_fixture_row(prowlarr_torrent_results, "dc comics : the flash")
    )

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Absolute Flash",
        wanted_issue=1.0,
        wanted_year=2025,
        wanted_issue_type=IssueType.ISSUE,
    )
    details = build_search_details(matched, rejected)

    assert matched == []
    assert len(rejected) == 1
    assert rejected[0].rejection_reason
    assert details["rejected_count"] == 1
    assert details["top_rejected"][0]["title"] == release.title


def test_absolute_wonder_woman_019_matches_from_prowlarr_fixture(
    prowlarr_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_prowlarr(_absolute_wonder_woman_019(prowlarr_issue_results))

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Absolute Wonder Woman",
        wanted_issue=19.0,
        wanted_year=2025,
        wanted_issue_type=IssueType.ISSUE,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].confidence.value == "high"
    assert matched[0].parsed.issue_number == 19.0


@pytest.mark.parametrize(
    ("source", "needle", "wanted_series", "wanted_issue", "wanted_year"),
    [
        ("nzb_issue", "Absolute Batman 2025 Annual 001", "Absolute Batman", 1.0, 2025),
        ("nzb_issue", "Batman Annual 005 HD", "Batman", 5.0, 1963),
        ("nzb_non", "White Ash-Annual 001", "White Ash", 1.0, 2024),
    ],
)
def test_real_fixture_annual_variants_match_parent_series(
    nzbgeek_issue_results: list[dict[str, object]],
    nzbgeek_non_issue_results: list[dict[str, object]],
    source: str,
    needle: str,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int,
) -> None:
    rows = nzbgeek_issue_results if source == "nzb_issue" else nzbgeek_non_issue_results
    release = _release_from_nzbgeek(_find_fixture_row(rows, needle))

    _assert_matches(
        release,
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_type=IssueType.ANNUAL,
    )


@pytest.mark.parametrize(
    ("source", "needle", "wanted_series", "wanted_year"),
    [
        (
            "nzb_issue",
            "ThunderCats X SilverHawks-Road to War",
            "ThunderCats X SilverHawks-Road to War",
            2026,
        ),
        (
            "pro_issue",
            "The Many Loves of the Amazing Spider-Man",
            "The Many Loves of the Amazing Spider-Man",
            None,
        ),
        (
            "nzb_issue",
            "Gargoyles x Fantastic Four",
            "Gargoyles x Fantastic Four",
            2025,
        ),
    ],
)
def test_real_fixture_one_shot_variants_match(
    nzbgeek_issue_results: list[dict[str, object]],
    prowlarr_issue_results: list[dict[str, object]],
    source: str,
    needle: str,
    wanted_series: str,
    wanted_year: int | None,
) -> None:
    if source == "pro_issue":
        release = _release_from_prowlarr(_find_fixture_row(prowlarr_issue_results, needle))
    else:
        release = _release_from_nzbgeek(_find_fixture_row(nzbgeek_issue_results, needle))

    _assert_matches(
        release,
        wanted_series=wanted_series,
        wanted_issue=1.0,
        wanted_year=wanted_year,
        wanted_type=IssueType.ONE_SHOT,
    )


@pytest.mark.parametrize(
    ("source", "needle", "wanted_series", "wanted_issue", "wanted_year"),
    [
        ("pro_non", "The Sandman v07 - Brief Lives", "The Sandman", 7.0, 2011),
        ("nzb_issue", "Invincible Vol. 9", "Invincible", 9.0, 2008),
        ("nzb_issue", "Absolute Batman v01-The Zoo", "Absolute Batman", 1.0, 2025),
    ],
)
def test_real_fixture_tpb_and_volume_variants_match(
    nzbgeek_issue_results: list[dict[str, object]],
    source: str,
    needle: str,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int,
) -> None:
    if source == "pro_non":
        release = _release_from_prowlarr(_find_fixture_row(_prowlarr_non_issue_results(), needle))
    else:
        release = _release_from_nzbgeek(_find_fixture_row(nzbgeek_issue_results, needle))

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_issue_type=IssueType.TPB,
    )

    assert rejected == []
    assert len(matched) == 1
    assert matched[0].parsed.issue_type in {IssueType.TPB, IssueType.VOLUME}
    assert score_release(release) > 0


@pytest.mark.parametrize(
    ("source", "needle", "wanted_series"),
    [
        ("pro_non", "V for Vendetta TPB (Extras Only)", "V for Vendetta"),
        ("nzb_non", "Donna Mia TPB", "Donna Mia"),
        ("pro_issue", "Saga, Vol 1-3", "Saga"),
    ],
)
def test_real_fixture_extras_only_releases_reject(
    nzbgeek_non_issue_results: list[dict[str, object]],
    prowlarr_issue_results: list[dict[str, object]],
    source: str,
    needle: str,
    wanted_series: str,
) -> None:
    rows_by_source = {
        "nzb_non": nzbgeek_non_issue_results,
        "pro_issue": prowlarr_issue_results,
        "pro_non": _prowlarr_non_issue_results(),
    }
    row = _find_fixture_row(rows_by_source[source], needle)
    release = (
        _release_from_prowlarr(row) if source.startswith("pro_") else _release_from_nzbgeek(row)
    )

    _assert_rejects(
        release,
        wanted_series=wanted_series,
        wanted_issue=1.0,
        wanted_year=None,
        wanted_type=IssueType.TPB,
        reason_contains="Contains ignore word",
    )


@pytest.mark.parametrize(
    ("needle", "wanted_series", "wanted_issue", "wanted_year"),
    [
        ("Invincible 1-101 + Atom Eve", "Invincible", 1.0, 2003),
        ("Ultimate X-Men (001 - 100", "Ultimate X-Men", 1.0, 2001),
    ],
)
def test_real_fixture_full_series_packs_do_not_satisfy_single_issue_targets(
    prowlarr_issue_results: list[dict[str, object]],
    needle: str,
    wanted_series: str,
    wanted_issue: float,
    wanted_year: int,
) -> None:
    release = _release_from_prowlarr(_find_fixture_row(prowlarr_issue_results, needle))

    _assert_rejects(
        release,
        wanted_series=wanted_series,
        wanted_issue=wanted_issue,
        wanted_year=wanted_year,
        wanted_type=IssueType.ISSUE,
        reason_contains="Multi-issue pack",
    )


def test_real_fixture_foreign_language_shorthand_is_penalized(
    prowlarr_issue_results: list[dict[str, object]],
) -> None:
    french_release = _release_from_prowlarr(
        _find_fixture_row(prowlarr_issue_results, "Absolute Batman T01 - 2025")
    )
    english_release = _release_from_prowlarr(
        _find_fixture_row(prowlarr_issue_results, "Absolute Batman v01-The Zoo")
    )

    assert _score_language(french_release.title, preferred="en") < 0
    assert score_release(french_release, preferred_language="en") < score_release(
        english_release,
        preferred_language="en",
    )
    assert score_release(french_release, preferred_language="fr") > score_release(
        french_release,
        preferred_language="en",
    )


def test_real_fixture_preview_edition_stays_rejected(
    prowlarr_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_prowlarr(
        _find_fixture_row(prowlarr_issue_results, "All In Access Preview Edition")
    )

    _assert_rejects(
        release,
        wanted_series="Absolute Batman",
        wanted_issue=1.0,
        wanted_year=2024,
        wanted_type=IssueType.ISSUE,
        reason_contains="Contains ignore word",
    )


def test_real_fixture_noir_edition_is_not_promoted_to_high_confidence(
    prowlarr_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_prowlarr(
        _find_fixture_row(prowlarr_issue_results, "Absolute.Batman.Noir.Edition.001")
    )

    matched, rejected = ReleaseValidator().validate_all_results(
        [release],
        wanted_series="Absolute Batman",
        wanted_issue=1.0,
        wanted_year=2025,
        wanted_issue_type=IssueType.ISSUE,
    )

    assert matched == []
    assert len(rejected) == 1
    assert rejected[0].confidence == MatchConfidence.LOW
    assert "Contains ignore word" in (rejected[0].rejection_reason or "")


def test_real_fixture_html_entities_normalize_for_series_matching(
    nzbgeek_issue_results: list[dict[str, object]],
) -> None:
    release = _release_from_nzbgeek(
        _find_fixture_row(nzbgeek_issue_results, "Invincible Presents Atom Eve &amp; Rex Splode")
    )

    _assert_matches(
        release,
        wanted_series="Invincible Presents Atom Eve Rex Splode",
        wanted_issue=2.0,
        wanted_year=2009,
        wanted_type=IssueType.ISSUE,
    )


@pytest.mark.parametrize(
    ("category", "is_comic"),
    [
        ("7030,100602", True),
        ("7000,7010,7020,7030", True),
        ("8000,8010,8020,10100000,9102000", False),
        ("Audio,Music", False),
    ],
)
def test_category_filtering_keeps_comic_rows_and_rejects_non_comic_rows(
    category: str,
    is_comic: bool,
) -> None:
    assert _is_comic_category(category) is is_comic


def test_search_details_caps_large_rejected_fixture_sets(
    prowlarr_issue_results: list[dict[str, object]],
) -> None:
    releases = [_release_from_prowlarr(row) for row in prowlarr_issue_results[:40]]

    matched, rejected = ReleaseValidator().validate_all_results(
        releases,
        wanted_series="Definitely Not This Series",
        wanted_issue=999.0,
        wanted_year=2026,
        wanted_issue_type=IssueType.ISSUE,
    )
    details = build_search_details(matched, rejected)

    assert matched == []
    assert len(rejected) > 25
    assert details["rejected_diagnostics_count"] == 25
    assert details["rejected_diagnostics_truncated"] is True
