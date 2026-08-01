"""Pure scheduler task-stat helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    """Optional logical status returned by a completed scheduler invocation."""

    status: Literal["completed", "waiting"] = "completed"


@dataclass
class TaskStats:
    """Accumulated stats for a single task."""

    last_execution: str | None = None
    last_duration_seconds: float | None = None
    last_status: str | None = None
    last_missed_at: str | None = None
    missed_count: int = 0
    last_overlap_at: str | None = None
    overlap_count: int = 0
    last_exclusive_block_at: str | None = None
    exclusive_block_count: int = 0
    running_since: str | None = None


def parse_stat_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO timestamp used in persisted scheduler stats."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def stats_from_row(row: Any) -> TaskStats:
    """Convert a DB row into TaskStats."""
    return TaskStats(
        last_execution=row.last_execution.isoformat() if row.last_execution else None,
        last_duration_seconds=row.last_duration_seconds,
        last_status=row.last_status,
        last_missed_at=row.last_missed_at.isoformat() if row.last_missed_at else None,
        missed_count=row.missed_count,
        last_overlap_at=row.last_overlap_at.isoformat() if row.last_overlap_at else None,
        overlap_count=row.overlap_count,
        last_exclusive_block_at=(
            row.last_exclusive_block_at.isoformat() if row.last_exclusive_block_at else None
        ),
        exclusive_block_count=row.exclusive_block_count,
    )


def stats_persisted_timestamp(stats: TaskStats) -> float | None:
    """Return the newest persisted stat timestamp as epoch seconds."""
    candidates = [
        parse_stat_timestamp(stats.last_execution),
        parse_stat_timestamp(stats.last_missed_at),
        parse_stat_timestamp(stats.last_overlap_at),
        parse_stat_timestamp(stats.last_exclusive_block_at),
    ]
    timestamps = [candidate.timestamp() for candidate in candidates if candidate is not None]
    if not timestamps:
        return None
    return max(timestamps)


def merge_stats_into(current: TaskStats, persisted: TaskStats) -> None:
    """Merge persisted stats into a task-stats snapshot in place."""
    current_ts = parse_stat_timestamp(current.last_execution)
    persisted_ts = parse_stat_timestamp(persisted.last_execution)
    if persisted_ts and (not current_ts or persisted_ts > current_ts):
        current.last_execution = persisted.last_execution
        current.last_duration_seconds = persisted.last_duration_seconds
        current.last_status = persisted.last_status
    elif not current.last_execution and persisted.last_execution:
        current.last_execution = persisted.last_execution

    if current.last_duration_seconds is None and persisted.last_duration_seconds is not None:
        current.last_duration_seconds = persisted.last_duration_seconds
    if not current.last_status and persisted.last_status:
        current.last_status = persisted.last_status
    current.missed_count = max(current.missed_count, persisted.missed_count)
    current.overlap_count = max(current.overlap_count, persisted.overlap_count)
    current.exclusive_block_count = max(
        current.exclusive_block_count, persisted.exclusive_block_count
    )

    current_missed = parse_stat_timestamp(current.last_missed_at)
    persisted_missed = parse_stat_timestamp(persisted.last_missed_at)
    if persisted_missed and (not current_missed or persisted_missed > current_missed):
        current.last_missed_at = persisted.last_missed_at

    current_overlap = parse_stat_timestamp(current.last_overlap_at)
    persisted_overlap = parse_stat_timestamp(persisted.last_overlap_at)
    if persisted_overlap and (not current_overlap or persisted_overlap > current_overlap):
        current.last_overlap_at = persisted.last_overlap_at

    current_exclusive_block = parse_stat_timestamp(current.last_exclusive_block_at)
    persisted_exclusive_block = parse_stat_timestamp(persisted.last_exclusive_block_at)
    if persisted_exclusive_block and (
        not current_exclusive_block or persisted_exclusive_block > current_exclusive_block
    ):
        current.last_exclusive_block_at = persisted.last_exclusive_block_at


def load_legacy_task_stats_sidecar(sidecar_path: Path) -> dict[str, TaskStats]:
    """Load task stats from the retired JSON sidecar format."""
    if not sidecar_path.exists():
        return {}
    try:
        raw = json.loads(sidecar_path.read_text())
    except (OSError, ValueError, TypeError):
        logger.warning("scheduler_task_stats_sidecar_invalid", path=str(sidecar_path))
        return {}
    if not isinstance(raw, dict):
        return {}
    loaded: dict[str, TaskStats] = {}
    for task_id, value in raw.items():
        if not isinstance(task_id, str) or not isinstance(value, dict):
            continue
        loaded[task_id] = TaskStats(
            last_execution=value.get("last_execution"),
            last_duration_seconds=value.get("last_duration_seconds"),
            last_status=value.get("last_status"),
            last_missed_at=value.get("last_missed_at"),
            missed_count=int(value.get("missed_count") or 0),
            last_overlap_at=value.get("last_overlap_at"),
            overlap_count=int(value.get("overlap_count") or 0),
            last_exclusive_block_at=value.get("last_exclusive_block_at"),
            exclusive_block_count=int(value.get("exclusive_block_count") or 0),
        )
    return loaded


def resolve_interval_seconds(trigger: str, trigger_kwargs: dict[str, Any]) -> int | None:
    """Resolve an interval trigger to total seconds, if possible."""
    if trigger != "interval":
        return None
    total = 0.0
    found = False
    for field, multiplier in (
        ("weeks", 7 * 24 * 60 * 60),
        ("days", 24 * 60 * 60),
        ("hours", 60 * 60),
        ("minutes", 60),
        ("seconds", 1),
    ):
        value = trigger_kwargs.get(field)
        if value is None:
            continue
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        total += amount * multiplier
        found = True
    if not found:
        return None
    return int(total)
