"""Helpers for suppressing repetitive expected warnings without hiding failures."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable


@dataclass
class _DedupState:
    """In-memory state for a deduplicated warning fingerprint."""

    last_emitted_at: float
    suppressed_count: int = 0


class WarningDeduper:
    """Deduplicate repeated warning events within a rolling time window."""

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._states: dict[Hashable, _DedupState] = {}

    def should_emit(self, key: Hashable, *, window_seconds: float) -> int | None:
        """Return suppressed count when a warning should emit, else ``None``."""
        now = self._now()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                self._states[key] = _DedupState(last_emitted_at=now)
                return 0
            if now - state.last_emitted_at < window_seconds:
                state.suppressed_count += 1
                return None
            suppressed_count = state.suppressed_count
            state.last_emitted_at = now
            state.suppressed_count = 0
            return suppressed_count


_warning_deduper = WarningDeduper()


def log_deduped_warning(
    logger: Any,
    event: str,
    *,
    key: Hashable,
    window_seconds: float = 300.0,
    **kwargs: Any,
) -> None:
    """Emit a warning only once per key/window, carrying suppressed-count metadata."""
    suppressed_count = _warning_deduper.should_emit(key, window_seconds=window_seconds)
    if suppressed_count is None:
        return
    payload = dict(kwargs)
    if suppressed_count:
        payload["suppressed_count"] = suppressed_count
    logger.warning(event, **payload)
