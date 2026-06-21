"""Tests for post-restore recovery marker and aftercare execution."""

from __future__ import annotations

import json
from typing import Any

import pytest


def test_mark_restore_recovery_pending_writes_marker_and_status(tmp_path):
    from pullbox.services.restore_recovery_service import (
        RESTORE_RECOVERY_MARKER_FILENAME,
        RESTORE_RECOVERY_STATUS_FILENAME,
        get_restore_recovery_status,
        mark_restore_recovery_pending,
    )

    status = mark_restore_recovery_pending(
        "pullbox_backup_20260620_120000.zip",
        data_dir=tmp_path,
    )

    marker_path = tmp_path / RESTORE_RECOVERY_MARKER_FILENAME
    status_path = tmp_path / RESTORE_RECOVERY_STATUS_FILENAME
    assert marker_path.is_file()
    assert status_path.is_file()
    assert status["status"] == "pending"
    assert status["restore_filename"] == "pullbox_backup_20260620_120000.zip"

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["restore_filename"] == "pullbox_backup_20260620_120000.zip"
    assert get_restore_recovery_status(data_dir=tmp_path)["status"] == "pending"


@pytest.mark.asyncio
async def test_restore_recovery_runs_steps_and_clears_marker(tmp_path, monkeypatch):
    from pullbox.services import restore_recovery_service as service

    calls: list[str] = []

    async def _cover_step() -> str:
        calls.append("covers")
        return "Cover cache checked."

    async def _issue_step() -> str:
        calls.append("issues")
        return "Issue catalog sync checked."

    async def _metadata_step() -> str:
        calls.append("metadata")
        return "Series metadata refresh checked."

    monkeypatch.setattr(service, "_run_cover_backfill_step", _cover_step)
    monkeypatch.setattr(service, "_run_issue_sync_step", _issue_step)
    monkeypatch.setattr(service, "_run_metadata_refresh_step", _metadata_step)

    service.mark_restore_recovery_pending("pullbox_backup.zip", data_dir=tmp_path)

    status = await service.run_restore_recovery_if_pending(data_dir=tmp_path)

    assert calls == ["covers", "issues", "metadata"]
    assert status is not None
    assert status["status"] == "completed"
    assert status["message"] == "Post-restore recovery completed."
    assert [step["status"] for step in status["steps"]] == [
        "completed",
        "completed",
        "completed",
    ]
    assert not (tmp_path / service.RESTORE_RECOVERY_MARKER_FILENAME).exists()
    assert service.get_restore_recovery_status(data_dir=tmp_path)["status"] == "completed"


@pytest.mark.asyncio
async def test_restore_recovery_records_attention_and_continues(tmp_path, monkeypatch):
    from pullbox.services import restore_recovery_service as service

    calls: list[str] = []

    async def _cover_step() -> str:
        calls.append("covers")
        return "Cover cache checked."

    async def _issue_step() -> str:
        calls.append("issues")
        raise RuntimeError("ComicVine unavailable")

    async def _metadata_step() -> str:
        calls.append("metadata")
        return "Series metadata refresh checked."

    monkeypatch.setattr(service, "_run_cover_backfill_step", _cover_step)
    monkeypatch.setattr(service, "_run_issue_sync_step", _issue_step)
    monkeypatch.setattr(service, "_run_metadata_refresh_step", _metadata_step)

    service.mark_restore_recovery_pending("pullbox_backup.zip", data_dir=tmp_path)

    status = await service.run_restore_recovery_if_pending(data_dir=tmp_path)

    assert calls == ["covers", "issues", "metadata"]
    assert status is not None
    assert status["status"] == "attention"
    assert "needs attention" in status["message"].lower()
    assert [step["status"] for step in status["steps"]] == [
        "completed",
        "failed",
        "completed",
    ]
    failed_step: dict[str, Any] = status["steps"][1]
    assert "ComicVine unavailable" in failed_step["message"]
    assert not (tmp_path / service.RESTORE_RECOVERY_MARKER_FILENAME).exists()


@pytest.mark.asyncio
async def test_restore_recovery_noops_without_marker(tmp_path):
    from pullbox.services.restore_recovery_service import run_restore_recovery_if_pending

    assert await run_restore_recovery_if_pending(data_dir=tmp_path) is None
