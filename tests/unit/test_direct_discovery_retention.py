from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectProviderConfig,
    DirectProviderState,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.services.direct_discovery_retention import (
    prune_unstarted_direct_discoveries,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_search_log_cleanup_prunes_only_unstarted_direct_discoveries(
    db_session: AsyncSession,
) -> None:
    series = Series(
        comicvine_id=990_001,
        title="Retention Series",
        sort_title="Retention Series",
        year_start=2026,
        status=SeriesStatus.CONTINUING,
        series_type=SeriesType.STANDARD,
        monitored=True,
        issue_count=1,
    )
    db_session.add(series)
    await db_session.flush()
    issue = Issue(
        series_id=series.id,
        comicvine_id=990_002,
        issue_number=1,
        issue_type=IssueType.ISSUE,
        status=IssueStatus.WANTED,
    )
    provider = DirectProviderConfig(
        provider_id="community.retention",
        display_name="Retention Provider",
        endpoint="http://provider:8080",
        enabled=True,
        priority=10,
        state=DirectProviderState.HEALTHY,
    )
    db_session.add_all([issue, provider])
    await db_session.flush()
    search_log = SearchLog(
        issue_id=issue.id,
        series_title=series.title,
        issue_number=1,
        search_type=SearchType.MANUAL,
    )
    db_session.add(search_log)
    await db_session.flush()
    discovered = DirectAcquisitionAttempt(
        request_key="retention:discovered",
        issue_id=issue.id,
        search_log_id=search_log.id,
        provider_config_id=provider.id,
        provider_identity=provider.provider_id,
        provider_candidate_id="candidate-discovered",
        state=DirectAcquisitionState.DISCOVERED,
    )
    completed = DirectAcquisitionAttempt(
        request_key="retention:completed",
        issue_id=issue.id,
        search_log_id=search_log.id,
        provider_config_id=provider.id,
        provider_identity=provider.provider_id,
        provider_candidate_id="candidate-completed",
        state=DirectAcquisitionState.COMPLETED,
    )
    db_session.add_all([discovered, completed])
    await db_session.commit()

    pruned = await prune_unstarted_direct_discoveries(
        db_session,
        select(SearchLog.id).where(SearchLog.id == search_log.id),
    )
    await db_session.execute(delete(SearchLog).where(SearchLog.id == search_log.id))
    await db_session.commit()

    remaining = (await db_session.execute(select(DirectAcquisitionAttempt))).scalars().all()
    assert pruned == 1
    assert [item.request_key for item in remaining] == ["retention:completed"]
