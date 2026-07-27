"""Operator lifecycle and bounded handoff for the shared browser resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select

from pullbox.models.direct_acquisition import (
    DirectProviderConfig,
    DirectProviderState,
    DirectResolverConfig,
    DirectResolverState,
)
from pullbox.providers.direct.contract import (
    DirectManifestResponse,
    DirectResolverProfile,
)
from pullbox.providers.direct.resolver import (
    DirectResolverClient,
    DirectResolverError,
    DirectResolverResult,
    ResolverCircuitBreaker,
)
from pullbox.services.direct_resolver_configuration import (
    DirectResolverConfigRead,
    load_resolver_auth_headers,
    read_resolver_config,
    update_resolver_auth_headers,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.providers.direct.endpoint import ValidatedProviderEndpoint

_RESOLVER_NAME = "default"
_TEST_TARGET = "https://example.com/"
_resolver_runtime: tuple[tuple[str, int], ResolverCircuitBreaker] | None = None


class DirectResolverServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DirectResolverUpdate:
    endpoint: str
    enabled: bool
    allow_private_http: bool = False
    timeout_seconds: int = 60
    max_concurrency: int = 1
    authentication_headers: Mapping[str, str | None] | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class DirectResolverTestResult:
    usable: bool
    state: DirectResolverState
    message: str
    checked_at: datetime


class DirectResolverClientProtocol(Protocol):
    async def validate_endpoint(self) -> ValidatedProviderEndpoint: ...

    async def solve(
        self,
        target_url: str,
        *,
        declared_domains: Sequence[str],
        challenge_category: str,
    ) -> DirectResolverResult: ...

    async def aclose(self) -> None: ...


class DirectResolverClientFactory(Protocol):
    def __call__(
        self,
        *,
        endpoint: str,
        allow_private_http: bool,
        authentication_headers: dict[str, str],
        timeout_seconds: float,
        max_concurrency: int,
        circuit_breaker: ResolverCircuitBreaker | None = None,
    ) -> DirectResolverClientProtocol: ...


def _default_client_factory(
    *,
    endpoint: str,
    allow_private_http: bool,
    authentication_headers: dict[str, str],
    timeout_seconds: float,
    max_concurrency: int,
    circuit_breaker: ResolverCircuitBreaker | None = None,
) -> DirectResolverClient:
    return DirectResolverClient(
        endpoint=endpoint,
        allow_private_http=allow_private_http,
        authentication_headers=authentication_headers,
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
        circuit_breaker=circuit_breaker,
    )


async def get_direct_resolver(session: AsyncSession) -> DirectResolverConfigRead:
    return read_resolver_config(await _get_or_create(session))


async def update_direct_resolver(
    session: AsyncSession,
    update: DirectResolverUpdate,
    *,
    client_factory: DirectResolverClientFactory = _default_client_factory,
) -> DirectResolverConfigRead:
    if update.timeout_seconds < 1 or update.timeout_seconds > 300:
        raise DirectResolverServiceError(
            "invalid_resolver_timeout",
            "Resolver timeout must be between 1 and 300 seconds.",
        )
    if update.max_concurrency < 1 or update.max_concurrency > 4:
        raise DirectResolverServiceError(
            "invalid_resolver_concurrency",
            "Resolver concurrency must be between 1 and 4.",
        )
    endpoint = update.endpoint.strip().rstrip("/")
    if update.enabled and not endpoint:
        raise DirectResolverServiceError(
            "resolver_endpoint_required",
            "Configure a resolver endpoint before enabling it.",
        )

    config = await _get_or_create(session)
    preview = DirectResolverConfig(
        name=_RESOLVER_NAME,
        endpoint=endpoint,
        enabled=update.enabled,
        state=config.state,
        allow_private_http=update.allow_private_http,
        timeout_seconds=update.timeout_seconds,
        max_concurrency=update.max_concurrency,
        encrypted_auth_headers=dict(config.encrypted_auth_headers or {}),
        auth_metadata=dict(config.auth_metadata or {}),
    )
    if update.authentication_headers is not None:
        update_resolver_auth_headers(preview, update.authentication_headers)
    auth_headers = load_resolver_auth_headers(preview).headers
    if endpoint:
        client = client_factory(
            endpoint=endpoint,
            allow_private_http=update.allow_private_http,
            authentication_headers=auth_headers,
            timeout_seconds=float(update.timeout_seconds),
            max_concurrency=update.max_concurrency,
        )
        try:
            validated = await client.validate_endpoint()
            endpoint = validated.url
        except DirectResolverError as exc:
            raise DirectResolverServiceError(exc.code, str(exc)) from exc
        finally:
            await client.aclose()

    config.endpoint = endpoint
    config.enabled = update.enabled
    config.allow_private_http = update.allow_private_http
    config.timeout_seconds = update.timeout_seconds
    config.max_concurrency = update.max_concurrency
    if update.authentication_headers is not None:
        update_resolver_auth_headers(config, update.authentication_headers)
    config.state = DirectResolverState.UNKNOWN if update.enabled else DirectResolverState.DISABLED
    config.last_health_at = None
    config.last_tested_at = None
    config.last_error_code = None
    await session.commit()
    _clear_resolver_runtime()
    await session.refresh(config)
    return read_resolver_config(config)


async def test_direct_resolver(
    session: AsyncSession,
    *,
    client_factory: DirectResolverClientFactory = _default_client_factory,
) -> DirectResolverTestResult:
    config = await _get_or_create(session)
    if not config.endpoint:
        raise DirectResolverServiceError(
            "resolver_endpoint_required",
            "Configure a resolver endpoint before testing it.",
        )
    checked_at = datetime.now(UTC)
    client = _client_for_config(config, client_factory)
    try:
        await client.solve(
            _TEST_TARGET,
            declared_domains=("example.com",),
            challenge_category="connection_test",
        )
    except DirectResolverError as exc:
        state = _state_for_error(exc.code)
        config.state = state
        config.last_tested_at = checked_at
        config.last_health_at = None
        config.last_error_code = exc.code
        await session.commit()
        return DirectResolverTestResult(
            usable=False,
            state=state,
            message=_test_failure_message(state),
            checked_at=checked_at,
        )
    finally:
        await client.aclose()

    config.state = DirectResolverState.HEALTHY
    config.last_tested_at = checked_at
    config.last_health_at = checked_at
    config.last_error_code = None
    await session.commit()
    return DirectResolverTestResult(
        usable=True,
        state=DirectResolverState.HEALTHY,
        message="Resolver returned a compatible standard /v1 response.",
        checked_at=checked_at,
    )


async def build_provider_resolver_profile(
    session: AsyncSession,
    provider: DirectProviderConfig,
) -> DirectResolverProfile | None:
    """Build a request-only profile after every global and provider gate passes."""
    if (
        not provider.enabled
        or provider.state not in {DirectProviderState.HEALTHY, DirectProviderState.DEGRADED}
        or not provider.resolver_enabled
    ):
        return None
    resolver = await session.scalar(
        select(DirectResolverConfig).where(DirectResolverConfig.name == _RESOLVER_NAME)
    )
    if (
        resolver is None
        or not resolver.enabled
        or resolver.state not in {DirectResolverState.HEALTHY, DirectResolverState.DEGRADED}
        or not resolver.endpoint
    ):
        return None
    try:
        manifest = DirectManifestResponse.model_validate(provider.manifest_snapshot)
    except ValueError:
        return None
    if not manifest.capabilities.browser_challenge or not manifest.source_domains:
        return None
    return DirectResolverProfile(
        endpoint=resolver.endpoint,
        mode="flaresolverr_v1",
        timeout_seconds=float(resolver.timeout_seconds),
        max_concurrency=resolver.max_concurrency,
        declared_domains=list(manifest.source_domains),
        authentication_headers=load_resolver_auth_headers(resolver).headers,
    )


async def resolve_for_host_adapter(
    session: AsyncSession,
    *,
    target_url: str,
    adapter_id: str,
    declared_domains: Sequence[str],
    challenge_category: str,
    client_factory: DirectResolverClientFactory = _default_client_factory,
) -> DirectResolverResult:
    """Use the resolver only through a code-owned host-adapter domain allowlist."""
    if not adapter_id or not declared_domains:
        raise DirectResolverServiceError(
            "resolver_adapter_policy_required",
            "Host adapter resolver use requires a static domain policy.",
        )
    config = await session.scalar(
        select(DirectResolverConfig).where(DirectResolverConfig.name == _RESOLVER_NAME)
    )
    if (
        config is None
        or not config.enabled
        or config.state not in {DirectResolverState.HEALTHY, DirectResolverState.DEGRADED}
    ):
        raise DirectResolverServiceError(
            "resolver_unavailable",
            "A healthy browser resolver is not configured.",
        )
    client = _client_for_config(config, client_factory)
    try:
        return await client.solve(
            target_url,
            declared_domains=declared_domains,
            challenge_category=challenge_category,
        )
    finally:
        await client.aclose()


async def _get_or_create(session: AsyncSession) -> DirectResolverConfig:
    config = await session.scalar(
        select(DirectResolverConfig).where(DirectResolverConfig.name == _RESOLVER_NAME)
    )
    if config is None:
        config = DirectResolverConfig(name=_RESOLVER_NAME)
        session.add(config)
        await session.flush()
    return config


def _client_for_config(
    config: DirectResolverConfig,
    factory: DirectResolverClientFactory,
) -> DirectResolverClientProtocol:
    return factory(
        endpoint=config.endpoint,
        allow_private_http=bool(config.allow_private_http),
        authentication_headers=load_resolver_auth_headers(config).headers,
        timeout_seconds=float(config.timeout_seconds),
        max_concurrency=config.max_concurrency,
        circuit_breaker=_get_resolver_runtime(config),
    )


def _get_resolver_runtime(config: DirectResolverConfig) -> ResolverCircuitBreaker:
    global _resolver_runtime

    key = (config.endpoint, config.max_concurrency)
    if _resolver_runtime is None or _resolver_runtime[0] != key:
        _resolver_runtime = (
            key,
            ResolverCircuitBreaker(max_concurrency=config.max_concurrency),
        )
    return _resolver_runtime[1]


def _clear_resolver_runtime() -> None:
    global _resolver_runtime

    _resolver_runtime = None


def _state_for_error(code: str) -> DirectResolverState:
    if "authentication" in code:
        return DirectResolverState.AUTHENTICATION_REQUIRED
    if "malformed" in code or "incompatible" in code:
        return DirectResolverState.INCOMPATIBLE
    return DirectResolverState.UNAVAILABLE


def _test_failure_message(state: DirectResolverState) -> str:
    if state is DirectResolverState.AUTHENTICATION_REQUIRED:
        return "Resolver rejected its configured authentication."
    if state is DirectResolverState.INCOMPATIBLE:
        return "Resolver did not return a compatible standard /v1 response."
    return "Resolver could not complete the bounded connection test."
