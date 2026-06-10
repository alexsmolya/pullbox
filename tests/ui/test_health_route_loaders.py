"""Tests for health route loader helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_load_health_overview_builds_presenter_from_shared_inputs() -> None:
    from pullbox.ui.health_route_loaders import load_health_overview

    session = object()
    components = [{"key": "database"}]
    health_view = object()
    load_health_data = AsyncMock(return_value=(components, "healthy"))
    get_search_stats = AsyncMock(return_value={"active": 1})
    build_health_view = AsyncMock(return_value=health_view)

    result = await load_health_overview(
        session,
        load_health_data=load_health_data,
        get_search_stats=get_search_stats,
        build_health_view=build_health_view,
    )

    assert result.overall_status == "healthy"
    assert result.health_view is health_view
    load_health_data.assert_awaited_once_with(session)
    get_search_stats.assert_awaited_once_with(session)
    build_health_view.assert_awaited_once_with(
        session,
        components=components,
        overall_status="healthy",
        search_stats={"active": 1},
    )


@pytest.mark.asyncio
async def test_load_health_overview_forwards_detail_view_options() -> None:
    from pullbox.ui.health_route_loaders import load_health_overview

    session = object()
    components = [{"key": "database"}]
    load_health_data = AsyncMock(return_value=(components, "degraded"))
    get_search_stats = AsyncMock(return_value={})
    build_health_view = AsyncMock(return_value=object())

    await load_health_overview(
        session,
        load_health_data=load_health_data,
        get_search_stats=get_search_stats,
        build_health_view=build_health_view,
        detail_component_key="database",
        detail_history_page=2,
        detail_history_sort="component",
        detail_history_search="sqlite",
    )

    build_health_view.assert_awaited_once_with(
        session,
        components=components,
        overall_status="degraded",
        search_stats={},
        detail_component_key="database",
        detail_history_page=2,
        detail_history_sort="component",
        detail_history_search="sqlite",
    )
