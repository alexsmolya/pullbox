"""Tests for human-readable startup banner and status messages."""

from __future__ import annotations

from pullbox.startup_messages import (
    StartupSummary,
    render_bootstrap_summary,
    render_ready_summary,
    render_restart_requested,
)


def test_render_bootstrap_summary_includes_banner_and_context() -> None:
    summary = StartupSummary(
        version="0.5.0-dev",
        release_date="2026-05-12",
        branch="feature/ui-followups",
        commit="abcdef1",
        base_url="http://localhost:8585",
        bind_address="0.0.0.0",
        port=8585,
        db_url="sqlite+aiosqlite:////data/pullbox.db",
        library_root="/comics",
        startup_log="/data/logs/startup.log",
    )

    rendered = render_bootstrap_summary(summary)

    assert "comic book management & acquisition" in rendered
    assert "[bootstrap] Pullbox v0.5.0-dev" in rendered
    assert "[bootstrap] Released: 2026-05-12" in rendered
    assert "[bootstrap] Branch: feature/ui-followups" in rendered
    assert "[bootstrap] Commit: abcdef1" in rendered
    assert "[bootstrap] Logs: /data/logs/startup.log" in rendered


def test_render_ready_summary_derives_ping_url() -> None:
    rendered = render_ready_summary(
        base_url="http://localhost:8585",
        scheduler_active=True,
    )

    assert "[ready] Pullbox is ready" in rendered
    assert "[ready] Open: http://localhost:8585" in rendered
    assert "[ready] Health: http://localhost:8585/ping" in rendered
    assert "[ready] Scheduler: active" in rendered


def test_render_restart_requested_mentions_exit_code() -> None:
    assert (
        render_restart_requested(42)
        == "[bootstrap] Restart requested (exit code 42), relaunching..."
    )
