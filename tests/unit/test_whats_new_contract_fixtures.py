from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SUMMARY_FIELDS = {
    "locg_issue_id",
    "locg_series_id",
    "locg_url",
    "title",
    "display_title",
    "issue_number",
    "price",
    "currency",
    "store_date",
    "release_week_date",
    "cover_url",
    "variant_count",
    "community_rating",
    "community_counts",
    "publisher",
    "series",
}
UNAVAILABLE_SUMMARY_FIELDS = {
    "comicvine_issue_id",
    "comicvine_series_id",
    "metron_issue_id",
    "metron_series_id",
    "gcd_issue_id",
    "gcd_series_id",
}


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _assert_release_summary_contract(issue: dict[str, Any]) -> None:
    assert set(issue) >= SUMMARY_FIELDS
    assert UNAVAILABLE_SUMMARY_FIELDS.isdisjoint(issue)

    assert set(issue["community_counts"]) == {
        "pull",
        "have",
        "read",
        "want",
        "pick",
    }
    assert {"name", "locg_publisher_id", "excluded", "excluded_reason"} <= set(issue["publisher"])
    assert {"title", "locg_series_id", "locg_url", "start_year", "volume"} <= set(issue["series"])


def test_current_week_fixture_locks_pullbox_data_release_summary_contract() -> None:
    payload = _load_fixture("pullbox_data_current_week.json")

    assert set(payload) == {"store_date", "count", "last_updated", "issues"}
    assert payload["count"] == len(payload["issues"])
    for issue in payload["issues"]:
        _assert_release_summary_contract(issue)


def test_upcoming_fixture_locks_pullbox_data_lookahead_contract() -> None:
    payload = _load_fixture("pullbox_data_upcoming.json")

    assert set(payload) == {"weeks", "lookahead_weeks"}
    assert payload["lookahead_weeks"] == len(payload["weeks"])
    for week in payload["weeks"]:
        assert set(week) == {"store_date", "count", "issues"}
        assert week["count"] == len(week["issues"])
        for issue in week["issues"]:
            _assert_release_summary_contract(issue)
