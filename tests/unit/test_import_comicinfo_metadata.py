"""Tests for ComicInfo metadata enrichment helpers."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from pullbox.models.issue import Issue
from pullbox.services.import_comicinfo_metadata import issue_needs_comicinfo_enrichment

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_issue_needs_comicinfo_enrichment_skips_complete_transient_issue(
    db_session: AsyncSession,
) -> None:
    issue = Issue(
        description="Already complete.",
        comicvine_url="https://comicvine.gamespot.com/example/4000-1/",
        release_date=date(2026, 1, 7),
    )

    assert await issue_needs_comicinfo_enrichment(db_session, issue) is False
