"""Lifecycle and profile-gating tests for the shared direct resolver."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from pullbox.core.encryption import _get_fernet
from pullbox.models.direct_acquisition import (
    DirectProviderConfig,
    DirectProviderState,
    DirectProviderTrustLevel,
    DirectResolverConfig,
    DirectResolverState,
)
from pullbox.providers.direct.contract import DIRECT_PROVIDER_PROTOCOL_V1
from pullbox.providers.direct.endpoint import ValidatedProviderEndpoint
from pullbox.providers.direct.resolver import (
    DirectResolverError,
    DirectResolverResult,
    ResolverCircuitBreaker,
)
from pullbox.services.direct_resolver_service import (
    DirectResolverServiceError,
    DirectResolverUpdate,
    build_provider_resolver_profile,
    get_direct_resolver,
    resolve_for_host_adapter,
    update_direct_resolver,
)
from pullbox.services.direct_resolver_service import (
    test_direct_resolver as run_direct_resolver_test,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _deterministic_application_secret() -> None:
    provider = MagicMock()
    provider.secret_key.return_value = "direct-resolver-lifecycle-secret"
    _get_fernet.cache_clear()
    with patch("pullbox.core.config_file.get_config_provider", return_value=provider):
        yield
    _get_fernet.cache_clear()


class _ResolverClient:
    error: ClassVar[DirectResolverError | None] = None
    seen: ClassVar[list[dict[str, object]]] = []
    solve_seen: ClassVar[list[tuple[tuple[object, ...], dict[str, object]]]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.seen.append(kwargs)

    async def validate_endpoint(self) -> ValidatedProviderEndpoint:
        return ValidatedProviderEndpoint(
            url="http://resolver:8191",
            host="resolver",
            port=8191,
            addresses=("172.20.0.9",),
            private_network=True,
            insecure_transport=True,
        )

    async def solve(self, *args: object, **kwargs: object) -> DirectResolverResult:
        self.solve_seen.append((args, kwargs))
        if self.error:
            raise self.error
        return DirectResolverResult(
            final_url="https://example.com/",
            status_code=200,
            html="<html>Example Domain</html>",
            cookies=(),
            user_agent="Resolver Browser",
        )

    async def aclose(self) -> None:
        return None


def _factory(**kwargs: object) -> _ResolverClient:
    return _ResolverClient(**kwargs)


def _manifest(*, browser_challenge: bool, domains: list[str]) -> dict[str, object]:
    return {
        "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
        "provider_id": "pullbox.test",
        "display_name": "Test Provider",
        "description": "Resolver profile fixture.",
        "provider_version": "1.0.0",
        "supported_protocol_versions": [DIRECT_PROVIDER_PROTOCOL_V1],
        "publisher": "Pullbox",
        "license": "GPL-3.0-or-later",
        "source_domains": domains,
        "capabilities": {
            "search": True,
            "resolve": True,
            "browser_challenge": browser_challenge,
            "health": True,
            "quota": False,
            "configuration_schema": False,
        },
        "configuration_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }


async def test_resolver_defaults_are_disabled_and_secret_free(
    db_session: AsyncSession,
) -> None:
    value = await get_direct_resolver(db_session)

    assert value.name == "default"
    assert value.enabled is False
    assert value.state is DirectResolverState.DISABLED
    assert value.endpoint == ""
    assert value.auth_headers_configured is False


async def test_update_normalizes_endpoint_encrypts_headers_and_requires_test(
    db_session: AsyncSession,
) -> None:
    _ResolverClient.seen = []
    value = await update_direct_resolver(
        db_session,
        DirectResolverUpdate(
            endpoint="http://resolver:8191/",
            enabled=True,
            allow_private_http=True,
            timeout_seconds=75,
            max_concurrency=2,
            authentication_headers={"X-API-Key": "resolver-secret"},
        ),
        client_factory=_factory,
    )

    assert value.endpoint == "http://resolver:8191"
    assert value.enabled is True
    assert value.state is DirectResolverState.UNKNOWN
    assert value.auth_header_names == ("X-API-Key",)
    row = await db_session.get(DirectResolverConfig, 1)
    assert row is not None
    assert "resolver-secret" not in str(row.encrypted_auth_headers)


async def test_successful_connection_test_marks_resolver_healthy(
    db_session: AsyncSession,
) -> None:
    _ResolverClient.error = None
    await update_direct_resolver(
        db_session,
        DirectResolverUpdate(
            endpoint="http://resolver:8191",
            enabled=True,
            allow_private_http=True,
            authentication_headers={"Authorization": "Bearer resolver-secret"},
        ),
        client_factory=_factory,
    )

    result = await run_direct_resolver_test(db_session, client_factory=_factory)

    assert result.usable is True
    assert result.state is DirectResolverState.HEALTHY
    assert result.checked_at.tzinfo is not None
    config = await db_session.get(DirectResolverConfig, 1)
    assert config is not None
    assert config.last_tested_at is not None
    assert config.last_health_at is not None
    assert config.last_error_code is None
    assert _ResolverClient.seen[-1]["authentication_headers"] == {
        "Authorization": "Bearer resolver-secret"
    }


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (
            DirectResolverError("resolver_authentication_failed", "Rejected authentication."),
            DirectResolverState.AUTHENTICATION_REQUIRED,
        ),
        (
            DirectResolverError("resolver_malformed_response", "Malformed response."),
            DirectResolverState.INCOMPATIBLE,
        ),
        (
            DirectResolverError("resolver_timed_out", "Timed out.", retryable=True),
            DirectResolverState.UNAVAILABLE,
        ),
    ],
)
async def test_connection_test_persists_only_classified_failure(
    db_session: AsyncSession,
    error: DirectResolverError,
    expected_state: DirectResolverState,
) -> None:
    await update_direct_resolver(
        db_session,
        DirectResolverUpdate(
            endpoint="http://resolver:8191",
            enabled=True,
            allow_private_http=True,
        ),
        client_factory=_factory,
    )
    _ResolverClient.error = error

    result = await run_direct_resolver_test(db_session, client_factory=_factory)

    assert result.usable is False
    assert result.state is expected_state
    config = await db_session.get(DirectResolverConfig, 1)
    assert config is not None
    assert config.last_error_code == error.code
    assert error.args[0] not in str(config.auth_metadata)
    _ResolverClient.error = None


async def test_provider_profile_requires_every_capability_and_opt_in_gate(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    resolver = DirectResolverConfig(
        name="default",
        endpoint="http://resolver:8191",
        enabled=True,
        state=DirectResolverState.HEALTHY,
        allow_private_http=True,
        timeout_seconds=45,
        max_concurrency=1,
        last_tested_at=now,
    )
    provider = DirectProviderConfig(
        provider_id="pullbox.test",
        display_name="Test Provider",
        endpoint="http://provider:8780",
        enabled=True,
        priority=10,
        state=DirectProviderState.HEALTHY,
        negotiated_protocol=DIRECT_PROVIDER_PROTOCOL_V1,
        trust_level=DirectProviderTrustLevel.VERIFIED_PULLBOX,
        encrypted_bearer_token="enc:not-used",
        resolver_enabled=True,
        manifest_snapshot=_manifest(
            browser_challenge=True,
            domains=["source.example", "cdn.source.example"],
        ),
    )
    db_session.add_all([resolver, provider])
    await db_session.commit()

    profile = await build_provider_resolver_profile(db_session, provider)

    assert profile is not None
    assert profile.endpoint == "http://resolver:8191"
    assert profile.declared_domains == ["source.example", "cdn.source.example"]
    assert profile.timeout_seconds == 45
    assert profile.max_concurrency == 1
    assert profile.authentication_headers == {}

    provider.resolver_enabled = False
    assert await build_provider_resolver_profile(db_session, provider) is None
    provider.resolver_enabled = True
    provider.manifest_snapshot = _manifest(browser_challenge=False, domains=["source.example"])
    assert await build_provider_resolver_profile(db_session, provider) is None
    provider.manifest_snapshot = _manifest(browser_challenge=True, domains=["source.example"])
    resolver.enabled = False
    assert await build_provider_resolver_profile(db_session, provider) is None


async def test_provider_profile_is_ephemeral_and_never_written_to_provider_row(
    db_session: AsyncSession,
) -> None:
    resolver = DirectResolverConfig(
        name="default",
        endpoint="http://resolver:8191",
        enabled=True,
        state=DirectResolverState.HEALTHY,
        allow_private_http=True,
        encrypted_auth_headers={},
    )
    provider = DirectProviderConfig(
        provider_id="pullbox.test",
        display_name="Test Provider",
        endpoint="http://provider:8780",
        enabled=True,
        state=DirectProviderState.HEALTHY,
        trust_level=DirectProviderTrustLevel.VERIFIED_PULLBOX,
        resolver_enabled=True,
        manifest_snapshot=_manifest(browser_challenge=True, domains=["source.example"]),
    )
    db_session.add_all([resolver, provider])
    await db_session.commit()

    profile = await build_provider_resolver_profile(db_session, provider)
    await db_session.refresh(provider)

    assert profile is not None
    assert "resolver" not in provider.configuration_metadata
    assert "resolver" not in provider.manifest_snapshot


async def test_host_adapter_resolution_uses_static_domain_policy_and_shared_breaker(
    db_session: AsyncSession,
) -> None:
    _ResolverClient.seen = []
    _ResolverClient.solve_seen = []
    resolver = DirectResolverConfig(
        name="default",
        endpoint="http://resolver:8191",
        enabled=True,
        state=DirectResolverState.HEALTHY,
        allow_private_http=True,
        max_concurrency=2,
    )
    db_session.add(resolver)
    await db_session.commit()

    for _ in range(2):
        await resolve_for_host_adapter(
            db_session,
            target_url="https://download.source.example/file",
            adapter_id="source-host",
            declared_domains=("source.example",),
            challenge_category="artifact_host_challenge",
            client_factory=_factory,
        )

    assert [call for call in _ResolverClient.solve_seen] == [
        (
            ("https://download.source.example/file",),
            {
                "declared_domains": ("source.example",),
                "challenge_category": "artifact_host_challenge",
            },
        ),
        (
            ("https://download.source.example/file",),
            {
                "declared_domains": ("source.example",),
                "challenge_category": "artifact_host_challenge",
            },
        ),
    ]
    first_breaker = _ResolverClient.seen[0]["circuit_breaker"]
    assert isinstance(first_breaker, ResolverCircuitBreaker)
    assert _ResolverClient.seen[1]["circuit_breaker"] is first_breaker


async def test_host_adapter_resolution_rejects_missing_policy(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(
        DirectResolverServiceError,
        match="requires a static domain policy",
    ):
        await resolve_for_host_adapter(
            db_session,
            target_url="https://source.example/file",
            adapter_id="",
            declared_domains=(),
            challenge_category="artifact_host_challenge",
            client_factory=_factory,
        )
