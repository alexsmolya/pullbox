"""Download progress state module characterization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def debug(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


def test_get_all_progress_returns_copy() -> None:
    """Callers should not mutate the live progress cache through snapshots."""
    from pullbox.tasks import download_progress

    download_progress._progress_cache.clear()
    snapshot = download_progress.ProgressSnapshot(
        progress=0.5,
        speed_bytes=100,
        eta_seconds=10,
        size_bytes=1_000,
        updated_at=123.0,
        client_state="Downloading",
    )
    download_progress._progress_cache[42] = snapshot

    copied = download_progress.get_all_progress()
    copied.clear()

    assert download_progress._progress_cache == {42: snapshot}
    download_progress._progress_cache.clear()


def test_clear_progress_clears_all_transient_state() -> None:
    """Progress cleanup should clear progress, milestones, stalls, and first-seen state."""
    from pullbox.tasks import download_progress

    download_progress._progress_cache[99] = download_progress.ProgressSnapshot(
        progress=0.25,
        speed_bytes=None,
        eta_seconds=None,
        size_bytes=None,
        updated_at=456.0,
    )
    download_progress._milestone_logged[99] = {25}
    download_progress._stall_first_seen[99] = 123.0
    download_progress._first_active_observed_at[99] = datetime.now(UTC)

    download_progress._clear_progress(99)

    assert 99 not in download_progress._progress_cache
    assert 99 not in download_progress._milestone_logged
    assert 99 not in download_progress._stall_first_seen
    assert 99 not in download_progress._first_active_observed_at


def test_record_download_progress_updates_progress_and_stall_state(
    monkeypatch,
) -> None:
    """Progress recording should own snapshot, milestone, and stall bookkeeping."""
    from pullbox.tasks import download_progress

    download_progress._clear_progress(7)
    fake_logger = _FakeLogger()
    times = iter([100.0, 101.0])
    monkeypatch.setattr(download_progress._time, "monotonic", lambda: next(times))

    status = SimpleNamespace(
        progress=0.75,
        speed_bytes=2048,
        eta_seconds=12,
        size_bytes=4096,
        client_state="metaDL waiting",
    )

    is_stall_state = download_progress.record_download_progress(
        7,
        status,
        event_logger=fake_logger,
    )

    snapshot = download_progress._progress_cache[7]
    assert is_stall_state is True
    assert snapshot.progress == 0.75
    assert snapshot.updated_at == 100.0
    assert download_progress._milestone_logged[7] == {25, 50, 75}
    assert download_progress._stall_first_seen[7] == 101.0
    assert 7 in download_progress._first_active_observed_at
    assert [payload["milestone_pct"] for _, payload in fake_logger.events] == [25, 50, 75]

    download_progress._clear_progress(7)
