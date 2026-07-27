"""Direct branch coverage for split settings UI route helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pullbox.models.client import DownloadClientConfig
from pullbox.models.config import SystemConfig
from pullbox.models.direct_acquisition import (
    DirectProviderConfig,
    DirectProviderState,
    DirectProviderTrustLevel,
)
from pullbox.models.download import DownloadClientType
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.ui import settings_routes

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RecordingTemplates:
    """Tiny template recorder so route tests can assert context directly."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette/Jinja2 template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        self.calls.append((template_name, context))
        return SimpleNamespace(template_name=template_name, context=context, status_code=200)


def _request(*, cookies: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies=cookies or {}, state=SimpleNamespace())


def _user() -> SimpleNamespace:
    return SimpleNamespace(username="admin")


@pytest.fixture
def configured_settings_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(settings_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        settings_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    monkeypatch.setattr(
        settings_routes,
        "_resolve_utility_browse_paths",
        lambda configs: {"trash": configs.get("utility_trash_folder", "/comics/.trash")},
    )
    return templates


@pytest.mark.asyncio
async def test_settings_runtime_seams_require_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_routes, "_get_templates", None)
    monkeypatch.setattr(settings_routes, "_build_context", None)
    monkeypatch.setattr(settings_routes, "_resolve_utility_browse_paths", None)

    with pytest.raises(RuntimeError, match="templates"):
        settings_routes._templates()
    with pytest.raises(RuntimeError, match="context builder"):
        settings_routes._ctx(_request())
    with pytest.raises(RuntimeError, match="utility browse paths"):
        settings_routes._utility_browse_paths({})

    assert settings_routes._normalize_settings_tab("nope") == "general"
    assert settings_routes._normalize_settings_tab("search") == "search"
    assert settings_routes._normalize_settings_tab("direct") == "direct"


def test_status_seed_helpers_prefer_live_state_then_cookie_cache() -> None:
    now = datetime.now(UTC)
    request = _request(
        cookies={
            "pb_client_status_cache": json.dumps({"3": {"healthy": True, "message": "Cached"}}),
            "pb_indexer_status_cache": json.dumps({"11": False}),
        }
    )
    clients = [
        DownloadClientConfig(
            id=1,
            name="Good",
            client_type=DownloadClientType.SABNZBD,
            url="http://sab",
            last_success_at=now,
            last_test_message=" OK ",
        ),
        DownloadClientConfig(
            id=2,
            name="Bad",
            client_type=DownloadClientType.QBITTORRENT,
            url="http://qbt",
            last_failure_at=now,
            last_error=" Broken ",
        ),
        DownloadClientConfig(
            id=3,
            name="Cached",
            client_type=DownloadClientType.NZBGET,
            url="http://nzbget",
        ),
    ]
    indexers = [
        IndexerConfig(
            id=10,
            name="Good",
            indexer_type=IndexerType.NEWZNAB,
            url="http://newznab",
            api_key="key",
            last_success_at=now,
        ),
        IndexerConfig(
            id=11,
            name="Cached",
            indexer_type=IndexerType.TORZNAB,
            url="http://torznab",
            api_key="key",
        ),
        IndexerConfig(
            id=12,
            name="Bad",
            indexer_type=IndexerType.PROWLARR,
            url="http://prowlarr",
            api_key="key",
            last_failure_at=now,
        ),
    ]

    client_seed = settings_routes.load_client_status_seed(request, clients)
    assert client_seed == {
        1: {"healthy": True, "message": "OK"},
        2: {"healthy": False, "message": "Broken"},
        3: {"healthy": True, "message": "Cached"},
    }

    indexer_seed = settings_routes.load_indexer_status_seed(request, indexers)
    assert indexer_seed == {10: True, 11: False, 12: False}

    invalid_cookie_request = _request(
        cookies={
            "pb_client_status_cache": "{",
            "pb_indexer_status_cache": "{",
        }
    )
    assert settings_routes.load_client_status_seed(invalid_cookie_request, [clients[2]]) == {}
    assert settings_routes.load_indexer_status_seed(invalid_cookie_request, [indexers[1]]) == {}


@pytest.mark.asyncio
async def test_load_settings_tab_covers_all_data_tabs(
    db_session: AsyncSession,
    configured_settings_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del configured_settings_routes
    now = datetime.now(UTC)
    db_session.add_all(
        [
            SystemConfig(key="instance_name", value="Pullbox Test"),
            SystemConfig(key="base_url", value="http://localhost:8585"),
            SystemConfig(key="comicvine_api_key", value="encrypted"),
            SystemConfig(key="prowlarr_api_key", value="not-encrypted"),
            SystemConfig(key="blocklist.release_groups", value="bad, worse"),
            SystemConfig(key="blocklist.expiry_days", value="30"),
            SystemConfig(key="blocklist.auto_add_on_failure", value="false"),
            SystemConfig(key="utility_trash_folder", value="/comics/.trash"),
            SystemConfig(key="utility_worker_count", value="2"),
            DownloadClientConfig(
                name="SAB",
                client_type=DownloadClientType.SABNZBD,
                url="http://sab",
                priority=1,
                last_success_at=now,
            ),
            IndexerConfig(
                name="Prowlarr",
                indexer_type=IndexerType.PROWLARR,
                url="http://prowlarr",
                api_key="stored",
                priority=1,
                last_failure_at=now - timedelta(minutes=1),
            ),
            DirectProviderConfig(
                provider_id="community.example",
                display_name="Example Direct Provider",
                endpoint="http://direct-provider:8780",
                priority=25,
                state=DirectProviderState.HEALTHY,
                trust_level=DirectProviderTrustLevel.CUSTOM,
                negotiated_protocol="direct-download-provider/v1",
                encrypted_bearer_token="encrypted-token-must-not-render",
                configuration_metadata={
                    "allow_private_http": True,
                    "public_values": {"result_limit": 20},
                    "configured_secret_fields": ["account_token"],
                },
                manifest_snapshot={
                    "protocol_version": "direct-download-provider/v1",
                    "provider_id": "community.example",
                    "display_name": "Example Direct Provider",
                    "description": "A provider fixture.",
                    "provider_version": "1.2.3",
                    "supported_protocol_versions": ["direct-download-provider/v1"],
                    "publisher": "Example Publisher",
                    "license": "MIT",
                    "source_domains": ["example.test"],
                    "capabilities": {
                        "search": True,
                        "resolve": True,
                        "health": True,
                        "configuration_schema": True,
                    },
                    "configuration_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "result_limit": {
                                "type": "integer",
                                "title": "Result limit",
                                "minimum": 1,
                                "maximum": 100,
                            },
                            "account_token": {
                                "type": "string",
                                "title": "Account token",
                                "x-pullbox-secret": True,
                            },
                        },
                    },
                },
            ),
        ]
    )
    await db_session.flush()
    monkeypatch.setattr(
        "pullbox.core.comicvine_key.get_comicvine_api_key",
        AsyncMock(return_value="abcdef123456"),
    )

    general = await settings_routes.load_settings_tab(_request(), db_session, "general")
    assert general["configs"]["instance_name"] == "Pullbox Test"  # type: ignore[index]
    assert general["identity"]["instance_name"] == "Pullbox Test"  # type: ignore[index]
    assert "runtime_info" in general
    assert "https_settings" in general

    media = await settings_routes.load_settings_tab(_request(), db_session, "media")
    assert "configs" in media
    assert media["host_info"]["library_root"]  # type: ignore[index]

    metadata = await settings_routes.load_settings_tab(_request(), db_session, "metadata")
    assert metadata["has_comicvine_key"] is True
    assert metadata["obfuscated_key"].endswith("3456")  # type: ignore[union-attr]

    search = await settings_routes.load_settings_tab(_request(), db_session, "search")
    assert search["configs"]["base_url"] == "http://localhost:8585"  # type: ignore[index]

    clients = await settings_routes.load_settings_tab(_request(), db_session, "clients")
    assert clients["clients"][0].name == "SAB"  # type: ignore[index]
    assert clients["client_status_seed"][1]["healthy"] is True  # type: ignore[index]
    assert "download_poll_interval_seconds" not in clients["configs"]  # type: ignore[operator]

    indexers = await settings_routes.load_settings_tab(_request(), db_session, "indexers")
    assert indexers["indexers"][0].name == "Prowlarr"  # type: ignore[index]
    assert indexers["indexer_status_seed"][1] is False  # type: ignore[index]
    assert indexers["configs"]["prowlarr_api_key"] == ""  # type: ignore[index]
    assert indexers["blocked_groups"] == ["bad", "worse"]
    assert indexers["blocklist_expiry_days"] == "30"
    assert indexers["blocklist_auto_add"] is False

    direct = await settings_routes.load_settings_tab(_request(), db_session, "direct")
    assert direct["direct_providers"][0].display_name == "Example Direct Provider"  # type: ignore[index]
    assert direct["direct_providers"][0].bearer_token_configured is True  # type: ignore[index]
    assert "encrypted-token-must-not-render" not in repr(direct["direct_providers"])

    utilities = await settings_routes.load_settings_tab(_request(), db_session, "utilities")
    assert utilities["configs"]["utility_worker_count"] == "2"  # type: ignore[index]
    assert utilities["utility_browse_paths"] == {"trash": "/comics/.trash"}

    ui = await settings_routes._load_settings_response_context(
        _request(),
        _user(),
        db_session,
        "ui",
    )
    assert ui["tab"] == "ui"
    assert "ui_settings" in ui
    assert "tz_env" in ui


@pytest.mark.asyncio
async def test_settings_page_and_htmx_routes_render_expected_templates(
    db_session: AsyncSession,
    configured_settings_routes: RecordingTemplates,
) -> None:
    page = await settings_routes.settings(
        _request(),
        _user(),
        db_session,
        tab="definitely-not-real",
    )
    assert page.template_name == "pages/settings.html"
    assert page.context["tab"] == "general"
    assert page.context["settings_tabs"] == settings_routes.SETTINGS_TABS

    htmx = await settings_routes.htmx_settings_tab(
        _request(),
        "search",
        _user(),
        db_session,
    )
    assert htmx.template_name == "partials/settings_content_bundle.html"
    assert htmx.context["tab"] == "search"
    assert configured_settings_routes.calls[-1][0] == "partials/settings_content_bundle.html"
