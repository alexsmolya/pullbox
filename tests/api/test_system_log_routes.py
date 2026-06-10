"""Route contract tests for system log API subrouter."""

from __future__ import annotations

from fastapi.routing import APIRoute

from pullbox.api.v1.system_log_routes import router


def test_system_log_subrouter_exposes_expected_paths() -> None:
    route_map = {
        (next(iter(route.methods)), route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    assert route_map == {
        ("GET", "/logs"),
        ("GET", "/logs/{filename}/content"),
        ("GET", "/logs/{filename}/download"),
        ("DELETE", "/logs/{filename}"),
        ("GET", "/logs/{filename}/stream"),
        ("DELETE", "/logs"),
    }
