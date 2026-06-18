"""Response-schema coverage for search log entries."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pullbox.models.search_log import SearchType
from pullbox.schemas.search_log import SearchLogItem


def test_search_log_item_serializes_search_summary_defaults() -> None:
    created_at = datetime(2026, 6, 17, 12, 30, tzinfo=UTC)

    item = SearchLogItem(
        id=42,
        issue_id=7,
        series_title="Absolute Superman",
        issue_number=14.0,
        search_type=SearchType.MANUAL,
        created_at=created_at,
    )

    assert item.model_dump() == {
        "id": 42,
        "issue_id": 7,
        "series_title": "Absolute Superman",
        "issue_number": 14.0,
        "search_type": SearchType.MANUAL,
        "results_found": 0,
        "results_grabbed": 0,
        "results_queued": 0,
        "results_rejected": 0,
        "details": {},
        "best_confidence": None,
        "created_at": created_at,
    }


def test_search_log_item_can_validate_from_orm_like_attributes() -> None:
    created_at = datetime(2026, 6, 17, 12, 45, tzinfo=UTC)

    item = SearchLogItem.model_validate(
        SimpleNamespace(
            id=43,
            issue_id=8,
            series_title="Absolute Superman",
            issue_number=12.0,
            search_type=SearchType.AUTOMATED,
            results_found=20,
            results_grabbed=1,
            results_queued=2,
            results_rejected=17,
            details={"source": "automatic"},
            best_confidence="HIGH",
            created_at=created_at,
        )
    )

    assert item.search_type is SearchType.AUTOMATED
    assert item.results_found == 20
    assert item.results_grabbed == 1
    assert item.results_queued == 2
    assert item.results_rejected == 17
    assert item.details == {"source": "automatic"}
    assert item.best_confidence == "HIGH"
