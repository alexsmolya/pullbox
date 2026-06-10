"""Tests for standalone scheduler task-stat helper functions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pullbox.core.scheduler_stats import (
    TaskStats,
    load_legacy_task_stats_sidecar,
    merge_stats_into,
    parse_stat_timestamp,
    resolve_interval_seconds,
    stats_from_row,
    stats_persisted_timestamp,
)


class _StatsRow:
    def __init__(self) -> None:
        self.last_execution = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
        self.last_duration_seconds = 2.5
        self.last_status = "completed"
        self.last_missed_at = datetime(2026, 6, 7, 11, 0, tzinfo=UTC)
        self.missed_count = 3
        self.last_overlap_at = datetime(2026, 6, 7, 11, 15, tzinfo=UTC)
        self.overlap_count = 4
        self.last_exclusive_block_at = datetime(2026, 6, 7, 11, 30, tzinfo=UTC)
        self.exclusive_block_count = 5


def test_stats_from_row_maps_all_persisted_fields() -> None:
    stats = stats_from_row(_StatsRow())

    assert stats.last_execution == "2026-06-07T12:00:00+00:00"
    assert stats.last_duration_seconds == 2.5
    assert stats.last_status == "completed"
    assert stats.last_missed_at == "2026-06-07T11:00:00+00:00"
    assert stats.missed_count == 3
    assert stats.last_overlap_at == "2026-06-07T11:15:00+00:00"
    assert stats.overlap_count == 4
    assert stats.last_exclusive_block_at == "2026-06-07T11:30:00+00:00"
    assert stats.exclusive_block_count == 5


def test_merge_stats_prefers_newer_execution_and_max_event_counts() -> None:
    older = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    newer = older + timedelta(hours=1)
    current = TaskStats(
        last_execution=older.isoformat(),
        last_duration_seconds=1.0,
        last_status="failed",
        missed_count=2,
        overlap_count=1,
    )
    persisted = TaskStats(
        last_execution=newer.isoformat(),
        last_duration_seconds=3.0,
        last_status="completed",
        last_missed_at=newer.isoformat(),
        missed_count=1,
        last_overlap_at=newer.isoformat(),
        overlap_count=5,
        last_exclusive_block_at=newer.isoformat(),
        exclusive_block_count=6,
    )

    merge_stats_into(current, persisted)

    assert current.last_execution == newer.isoformat()
    assert current.last_duration_seconds == 3.0
    assert current.last_status == "completed"
    assert current.missed_count == 2
    assert current.overlap_count == 5
    assert current.exclusive_block_count == 6
    assert current.last_missed_at == newer.isoformat()
    assert current.last_overlap_at == newer.isoformat()
    assert current.last_exclusive_block_at == newer.isoformat()


def test_legacy_sidecar_loader_ignores_invalid_payloads_and_maps_valid_rows(
    tmp_path,
) -> None:
    path = tmp_path / "scheduled_task_stats.json"
    path.write_text("{not-json")
    assert load_legacy_task_stats_sidecar(path) == {}

    payload: dict[str, Any] = {
        "sync_new_issues": {
            "last_execution": "2026-06-07T12:00:00+00:00",
            "last_duration_seconds": 1.25,
            "last_status": "completed",
            "missed_count": "2",
            "overlap_count": "3",
            "exclusive_block_count": "4",
        },
        "bad-value": "ignored",
    }
    path.write_text(json.dumps(payload))

    loaded = load_legacy_task_stats_sidecar(path)

    assert sorted(loaded) == ["sync_new_issues"]
    assert loaded["sync_new_issues"].last_status == "completed"
    assert loaded["sync_new_issues"].missed_count == 2
    assert loaded["sync_new_issues"].overlap_count == 3
    assert loaded["sync_new_issues"].exclusive_block_count == 4


def test_timestamp_and_interval_helpers_handle_invalid_values() -> None:
    stats = TaskStats(
        last_execution="2026-06-07T12:00:00+00:00",
        last_overlap_at="2026-06-07T12:05:00+00:00",
    )

    assert parse_stat_timestamp("not-a-timestamp") is None
    assert stats_persisted_timestamp(TaskStats()) is None
    assert stats_persisted_timestamp(stats) == datetime(2026, 6, 7, 12, 5, tzinfo=UTC).timestamp()
    assert resolve_interval_seconds("cron", {"hours": 1}) is None
    assert resolve_interval_seconds("interval", {"hours": "bad"}) is None
    assert resolve_interval_seconds("interval", {"minutes": 2, "seconds": 30}) == 150
