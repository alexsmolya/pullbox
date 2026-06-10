"""Route contract tests for import orphaned API subrouter."""

from __future__ import annotations

from fastapi.routing import APIRoute

from pullbox.api.v1.import_job_orphaned_routes import router


def test_orphaned_subrouter_exposes_expected_paths() -> None:
    route_map = {
        (next(iter(route.methods)), route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    assert route_map == {
        ("GET", "/orphaned"),
        ("GET", "/orphaned/count"),
        ("POST", "/orphaned/{imported_series_id}/assign"),
        ("GET", "/orphaned/{imported_series_id}/recovery"),
        ("POST", "/orphaned/{imported_series_id}/recover"),
        ("POST", "/orphaned/{imported_series_id}/recover/start"),
        ("GET", "/orphaned/{imported_series_id}/recover/progress"),
        ("POST", "/orphaned/{imported_series_id}/dismiss"),
    }
