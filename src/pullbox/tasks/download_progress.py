"""Transient download progress and stall-tracking state."""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ProgressSnapshot:
    """Point-in-time progress from a download client. In-memory only."""

    progress: float  # 0.0 to 1.0
    speed_bytes: int | None
    eta_seconds: int | None
    size_bytes: int | None
    updated_at: float
    client_state: str | None = None


# Client-reported states that indicate a stall (case-insensitive prefix match).
_STALL_CLIENT_STATES = frozenset({"stalled", "metadl", "fetching"})

# In-memory state is transient and UI/recovery only.
_progress_cache: dict[int, ProgressSnapshot] = {}
_stall_first_seen: dict[int, float] = {}
_milestone_logged: dict[int, set[int]] = {}
_first_active_observed_at: dict[int, datetime] = {}
_MILESTONES = (25, 50, 75, 100)


def get_all_progress() -> dict[int, ProgressSnapshot]:
    """Return a shallow copy of the live progress cache."""
    return dict(_progress_cache)


def _clear_progress(download_id: int) -> None:
    """Remove a download from progress and stall-tracking caches."""
    _progress_cache.pop(download_id, None)
    _milestone_logged.pop(download_id, None)
    _stall_first_seen.pop(download_id, None)
    _first_active_observed_at.pop(download_id, None)


def record_download_progress(
    download_id: int,
    status: Any,
    *,
    event_logger: Any | None = None,
) -> bool:
    """Record live progress, milestones, and client-state stall tracking."""
    _first_active_observed_at.setdefault(download_id, datetime.now(UTC))

    _progress_cache[download_id] = ProgressSnapshot(
        progress=status.progress,
        speed_bytes=status.speed_bytes,
        eta_seconds=status.eta_seconds,
        size_bytes=status.size_bytes,
        updated_at=_time.monotonic(),
        client_state=status.client_state,
    )

    pct = int(status.progress * 100)
    logged = _milestone_logged.setdefault(download_id, set())
    for milestone in _MILESTONES:
        if pct >= milestone and milestone not in logged:
            logged.add(milestone)
            if event_logger is not None:
                event_logger.debug(
                    "download_progress_milestone",
                    download_id=download_id,
                    milestone_pct=milestone,
                    speed_bytes=status.speed_bytes,
                    size_bytes=status.size_bytes,
                    eta_seconds=status.eta_seconds,
                )

    is_stall_state = False
    if status.client_state:
        lower = status.client_state.lower()
        is_stall_state = any(lower.startswith(s) for s in _STALL_CLIENT_STATES)

    if is_stall_state:
        _stall_first_seen.setdefault(download_id, _time.monotonic())
    else:
        _stall_first_seen.pop(download_id, None)

    return is_stall_state
