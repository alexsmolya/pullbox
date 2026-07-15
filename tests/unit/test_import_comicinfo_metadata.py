"""Tests for ComicInfo metadata enrichment helpers."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from pullbox.core.exceptions import ProviderError
from pullbox.models.issue import Issue
from pullbox.services.import_comicinfo_metadata import (
    enrich_issue_for_comicinfo,
    issue_needs_comicinfo_enrichment,
)

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


@pytest.mark.asyncio
async def test_enrich_issue_propagates_sqlite_lock_for_outer_retry(
    db_session: AsyncSession,
) -> None:
    issue = Issue(comicvine_id=1234)
    lock_error = OperationalError(
        "UPDATE issues SET description = ?",
        {},
        Exception("database is locked"),
    )
    metadata_service = AsyncMock()
    metadata_service.fetch_issue.side_effect = lock_error

    with pytest.raises(OperationalError, match="database is locked"):
        await enrich_issue_for_comicinfo(
            db_session,
            issue,
            metadata_service=metadata_service,
        )


@pytest.mark.asyncio
async def test_enrich_issue_propagates_retryable_provider_error_when_required(
    db_session: AsyncSession,
) -> None:
    issue = Issue(comicvine_id=1234)
    provider_error = ProviderError(
        "comicvine",
        "HTTP 420: /issue/4000-1234/",
        details={"status_code": 420, "retryable": True},
    )
    metadata_service = AsyncMock()
    metadata_service.fetch_issue.side_effect = provider_error

    with pytest.raises(ProviderError, match="HTTP 420"):
        await enrich_issue_for_comicinfo(
            db_session,
            issue,
            metadata_service=metadata_service,
            propagate_retryable_provider_errors=True,
        )


@pytest.mark.asyncio
async def test_enrich_issue_still_tolerates_retryable_provider_error_by_default(
    db_session: AsyncSession,
) -> None:
    issue = Issue(comicvine_id=1234)
    metadata_service = AsyncMock()
    metadata_service.fetch_issue.side_effect = ProviderError(
        "comicvine",
        "HTTP 420: /issue/4000-1234/",
        details={"status_code": 420, "retryable": True},
    )

    enriched = await enrich_issue_for_comicinfo(
        db_session,
        issue,
        metadata_service=metadata_service,
    )

    assert enriched is issue
