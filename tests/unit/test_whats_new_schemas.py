"""Tests for What's New internal response schemas."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pullbox.schemas.whats_new import (
    WhatsNewCacheMetadata,
    WhatsNewCurrentWeekResponse,
    WhatsNewUpcomingResponse,
)

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


class TestWhatsNewSchemas:
    def test_current_week_schema_accepts_upstream_summary_fixture(self) -> None:
        payload = _load_fixture("pullbox_data_current_week.json")

        response = WhatsNewCurrentWeekResponse(
            **payload,
            cache=WhatsNewCacheMetadata(
                status="fresh",
                fetched_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                last_successful_refresh_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                stale=False,
            ),
        )

        assert response.store_date == date(2026, 3, 11)
        assert response.count == 2
        assert response.issues[0].locg_issue_id == 1511525
        assert response.issues[0].publisher.name == "DC Comics"
        assert response.issues[0].series.title == "Absolute Batman"
        assert response.issues[0].release_week_date == date(2026, 3, 4)
        assert response.issues[0].community_counts.pull == 2500
        assert response.cache.status == "fresh"

    def test_upcoming_schema_accepts_upstream_summary_fixture(self) -> None:
        payload = _load_fixture("pullbox_data_upcoming.json")

        response = WhatsNewUpcomingResponse(
            **payload,
            cache=WhatsNewCacheMetadata(
                status="stale",
                fetched_at=datetime(2026, 5, 16, 5, 0, tzinfo=UTC),
                last_successful_refresh_at=datetime(2026, 5, 16, 5, 0, tzinfo=UTC),
                stale=True,
            ),
        )

        assert response.lookahead_weeks == 2
        assert response.weeks[0].store_date == date(2026, 3, 18)
        assert response.weeks[1].issues[0].title == "Absolute Flash #1"
        assert response.weeks[1].issues[0].store_date == date(2026, 3, 25)
        assert response.weeks[1].issues[0].release_week_date == date(2026, 3, 18)
        assert response.weeks[1].issues[0].community_rating is None
        assert response.cache.status == "stale"

    def test_schema_serialization_uses_json_safe_dates_and_aliases(self) -> None:
        payload = _load_fixture("pullbox_data_current_week.json")
        response = WhatsNewCurrentWeekResponse(
            **payload,
            cache=WhatsNewCacheMetadata(
                status="fresh",
                fetched_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                last_successful_refresh_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                stale=False,
            ),
        )

        dumped = response.model_dump(mode="json")

        assert dumped["store_date"] == "2026-03-11"
        assert dumped["issues"][0]["release_week_date"] == "2026-03-04"
        assert dumped["last_updated"] == "2026-03-10T12:15:00Z"
        assert dumped["cache"]["fetched_at"] == "2026-05-16T12:00:00Z"
        assert "comicvine_id" not in dumped["issues"][0]
        assert "metron_id" not in dumped["issues"][0]
        assert "gcd_id" not in dumped["issues"][0]

    def test_schema_accepts_legacy_cached_payload_without_release_week_date(self) -> None:
        payload = _load_fixture("pullbox_data_current_week.json")
        issues = payload["issues"]
        assert isinstance(issues, list)
        first_issue = issues[0]
        assert isinstance(first_issue, dict)
        first_issue.pop("release_week_date", None)

        response = WhatsNewCurrentWeekResponse(
            **payload,
            cache=WhatsNewCacheMetadata(
                status="fresh",
                fetched_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                last_successful_refresh_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                stale=False,
            ),
        )

        assert response.issues[0].release_week_date is None
