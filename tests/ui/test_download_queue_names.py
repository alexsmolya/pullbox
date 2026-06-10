"""Tests for downloads queue display-name helper."""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueType
from pullbox.models.series import Series
from pullbox.ui.download_queue_names import build_queue_names

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-download-queue-names")


@pytest.mark.asyncio
async def test_build_queue_names_returns_template_stem_for_linked_issue(sec_db) -> None:  # type: ignore[no-untyped-def]
    async with sec_db() as session:
        series = Series(title="Batman", sort_title="batman", year_start=2026)
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            issue_number=2.0,
            title="Night Moves",
            issue_type=IssueType.ISSUE,
        )
        session.add(issue)
        await session.flush()

        download = DownloadHistory(
            title="Batman 002 (2026) (Digital).cbz",
            state=DownloadState.DOWNLOADING,
            download_client=DownloadClientType.SABNZBD,
            download_url="https://example.com/batman-002.nzb",
            issue_id=issue.id,
        )
        session.add(download)
        await session.commit()

    async with sec_db() as session:
        result = await session.execute(
            select(DownloadHistory).options(
                joinedload(DownloadHistory.issue).joinedload(Issue.series)
            )
        )
        downloads = list(result.scalars().all())
        names = await build_queue_names(session, downloads)

    assert names == {downloads[0].id: "Batman (2026) #002"}
