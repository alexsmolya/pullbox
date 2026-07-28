"""Unified issue search keeps direct and legacy source behavior isolated."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pullbox.models.issue import IssueType
from pullbox.providers.base import ProviderRegistry
from pullbox.services.direct_search_coordinator import (
    DirectSearchOutcome,
    DirectSearchProvider,
)
from pullbox.services.search_service import SearchService
from pullbox.services.search_targets import IssueSearchTarget

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _target() -> IssueSearchTarget:
    return IssueSearchTarget(
        issue_id=71,
        series_id=17,
        series_title="Absolute Superman",
        issue_number=9,
        issue_type=IssueType.ISSUE,
        series_year=2025,
    )


def _provider() -> DirectSearchProvider:
    return DirectSearchProvider(
        provider_config_id=1,
        provider_identity="pullbox.getcomics",
        display_name="GetComics",
        endpoint="http://getcomics-provider:8780",
        bearer_token="provider-token-with-enough-length",
        allow_private_http=True,
    )


async def test_unified_search_runs_direct_and_indexers_concurrently(
    db_session: AsyncSession,
) -> None:
    indexer_started = asyncio.Event()
    direct_started = asyncio.Event()

    async def run_indexers(*_args: object, **_kwargs: object):
        indexer_started.set()
        await asyncio.wait_for(direct_started.wait(), timeout=1)
        return [], {}, []

    direct_outcome = DirectSearchOutcome((), (), (), 1, 4)

    async def run_direct(*_args: object, **_kwargs: object) -> DirectSearchOutcome:
        direct_started.set()
        await asyncio.wait_for(indexer_started.wait(), timeout=1)
        return direct_outcome

    service = SearchService(
        ProviderRegistry(),
        direct_providers=(_provider(),),
        direct_search_func=run_direct,
    )
    service._run_query_batch_with_provenance = run_indexers  # type: ignore[method-assign]

    outcome = await service.search_issue_target(db_session, _target(), mode="fast")

    assert outcome.direct_outcome is direct_outcome


async def test_quick_first_deep_fallback_searches_direct_provider_only_once(
    db_session: AsyncSession,
) -> None:
    direct_calls = 0
    indexer_calls = 0

    async def run_indexers(*_args: object, **_kwargs: object):
        nonlocal indexer_calls
        indexer_calls += 1
        return [], {}, []

    async def run_direct(*_args: object, **_kwargs: object) -> DirectSearchOutcome:
        nonlocal direct_calls
        direct_calls += 1
        return DirectSearchOutcome((), (), (), 1, 2)

    service = SearchService(
        ProviderRegistry(),
        direct_providers=(_provider(),),
        direct_search_func=run_direct,
    )
    service._run_query_batch_with_provenance = run_indexers  # type: ignore[method-assign]

    outcome = await service.search_issue_target_quick_first(db_session, _target())

    assert outcome.search_details["search_strategy"] == "quick_first_deep_fallback"
    assert indexer_calls == 3
    assert direct_calls == 1
    assert outcome.direct_outcome is not None
