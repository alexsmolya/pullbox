"""Tests for OpenAPI exposure — operator routes stay hidden from public docs."""

from __future__ import annotations

import os

from pullbox.api.v1.audit import router as audit_router
from pullbox.api.v1.auth import router as auth_router
from pullbox.api.v1.clients import router as clients_router
from pullbox.api.v1.config import router as config_router
from pullbox.api.v1.covers import router as covers_router
from pullbox.api.v1.filesystem import router as filesystem_router
from pullbox.api.v1.health import router as health_router
from pullbox.api.v1.indexers import router as indexers_router
from pullbox.api.v1.library import router as library_router
from pullbox.api.v1.series import router as series_router
from pullbox.api.v1.system import router as system_router
from pullbox.app import create_app
from pullbox.utilities.router import router as utilities_router

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-schema-exposure")


class TestSchemaExposure:
    """Operator-only endpoints should be absent from the public schema."""

    def test_operator_routers_hidden(self) -> None:
        assert audit_router.include_in_schema is False
        assert clients_router.include_in_schema is False
        assert config_router.include_in_schema is False
        assert covers_router.include_in_schema is False
        assert filesystem_router.include_in_schema is False
        assert health_router.include_in_schema is False
        assert indexers_router.include_in_schema is False
        assert library_router.include_in_schema is False
        assert system_router.include_in_schema is False
        assert utilities_router.include_in_schema is False

    def test_public_and_automation_routers_remain_visible(self) -> None:
        assert auth_router.include_in_schema is True
        assert series_router.include_in_schema is True

    def test_openapi_excludes_operator_routes(self) -> None:
        schema = create_app().openapi()
        paths = schema["paths"]

        assert "/api/v1/auth/login" in paths
        assert "/api/v1/system/setup" in paths
        assert "/api/v1/series" in paths

        assert "/api/v1/auth/apikeys" not in paths
        assert "/api/v1/audit/events" not in paths
        assert "/api/v1/config" not in paths
        assert "/api/v1/filesystem/browse" not in paths
        assert "/api/v1/health" not in paths
        assert "/api/v1/indexers" not in paths
        assert "/api/v1/library/unmatched" not in paths
        assert "/api/v1/library/browser/entry" not in paths
        assert "/api/v1/system/about" not in paths
        assert "/api/v1/utilities/jobs" not in paths
        assert "/api/v1/series/{series_id}/cover" not in paths
