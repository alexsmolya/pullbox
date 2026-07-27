"""Bounded FlareSolverr-compatible client for browser challenge resolution."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pullbox.providers.direct.endpoint import (
    ProviderEndpointError,
    ProviderEndpointResolver,
    ValidatedProviderEndpoint,
    validate_provider_endpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

logger = structlog.get_logger(__name__)

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_HTML_CHARS = 8 * 1024 * 1024
_MAX_DECLARED_DOMAINS = 100
_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "proxy-authenticate",
        "proxy-authorization",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class DirectResolverError(RuntimeError):
    """Classified resolver failure containing no source or auth secrets."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ValidatedResolverTarget:
    url: str = field(repr=False)
    host: str


@dataclass(frozen=True, slots=True)
class DirectResolverCookie:
    name: str
    value: str = field(repr=False)
    domain: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class DirectResolverResult:
    final_url: str = field(repr=False)
    status_code: int
    html: str = field(repr=False)
    cookies: tuple[DirectResolverCookie, ...] = field(repr=False)
    user_agent: str | None = field(default=None, repr=False)


class _ResolverCookieModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=256)
    value: str = Field(max_length=16_384)
    domain: str | None = Field(default=None, max_length=500)
    path: str | None = Field(default=None, max_length=2_000)


class _ResolverSolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1, max_length=4_000)
    status: int = Field(ge=100, le=599)
    response: str = Field(max_length=_MAX_HTML_CHARS)
    cookies: list[_ResolverCookieModel] = Field(default_factory=list, max_length=200)
    user_agent: str | None = Field(default=None, alias="userAgent", max_length=2_000)


class _ResolverResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["ok"]
    message: str | None = Field(default=None, max_length=2_000)
    solution: _ResolverSolution


class ResolverCircuitBreaker:
    """Fail-fast process-local breaker with a bounded active request count."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        max_concurrency: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("Resolver failure threshold must be positive.")
        if cooldown_seconds <= 0:
            raise ValueError("Resolver cooldown must be positive.")
        if max_concurrency < 1 or max_concurrency > 4:
            raise ValueError("Resolver concurrency must be between 1 and 4.")
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._max_concurrency = max_concurrency
        self._clock = clock
        self._lock = asyncio.Lock()
        self._active = 0
        self._failures = 0
        self._state = "closed"
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        return self._state

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._lock:
            if self._state == "open":
                assert self._opened_at is not None
                if self._clock() - self._opened_at < self._cooldown_seconds:
                    raise DirectResolverError(
                        "resolver_circuit_open",
                        "Resolver is temporarily unavailable while its circuit recovers.",
                        retryable=True,
                    )
                self._state = "half_open"
            if self._active >= self._max_concurrency or (
                self._state == "half_open" and self._active > 0
            ):
                raise DirectResolverError(
                    "resolver_busy",
                    "Resolver concurrency is currently full; retry later.",
                    retryable=True,
                )
            self._active += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active -= 1

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None
            self._state = "closed"

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = self._clock()
                self._state = "open"


class DirectResolverClient:
    """Perform a single standard ``request.get`` through a validated resolver."""

    def __init__(
        self,
        *,
        endpoint: str,
        allow_private_http: bool = False,
        authentication_headers: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        max_concurrency: int = 1,
        endpoint_resolver: ProviderEndpointResolver | None = None,
        target_resolver: ProviderEndpointResolver | None = None,
        http_client: httpx.AsyncClient | None = None,
        circuit_breaker: ResolverCircuitBreaker | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Resolver timeout must be between 0 and 300 seconds.")
        self._endpoint = endpoint
        self._allow_private_http = allow_private_http
        self._authentication_headers = _validated_auth_headers(authentication_headers or {})
        self._timeout_seconds = timeout_seconds
        self._endpoint_resolver = endpoint_resolver
        self._target_resolver = target_resolver
        self._breaker = circuit_breaker or ResolverCircuitBreaker(max_concurrency=max_concurrency)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=timeout_seconds, write=10.0, pool=5.0),
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return f"DirectResolverClient(endpoint={self._endpoint!r})"

    async def __aenter__(self) -> DirectResolverClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def validate_endpoint(self) -> ValidatedProviderEndpoint:
        """Apply the resolver endpoint policy without performing a solve."""
        return await self._validate_endpoint()

    async def solve(
        self,
        target_url: str,
        *,
        declared_domains: Sequence[str],
        challenge_category: str,
    ) -> DirectResolverResult:
        target = await validate_resolver_target(
            target_url,
            declared_domains=declared_domains,
            resolver=self._target_resolver,
        )
        started_at = time.monotonic()
        try:
            async with self._breaker.slot():
                result = await self._perform(target, tuple(declared_domains))
                await self._breaker.record_success()
        except asyncio.CancelledError:
            logger.info(
                "direct_resolver_request_cancelled",
                source_domain=target.host,
                challenge_category=challenge_category,
                circuit_state=self._breaker.state,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            )
            raise
        except DirectResolverError as exc:
            if exc.code not in {
                "resolver_busy",
                "resolver_circuit_open",
                "resolver_redirect_rejected",
                "resolver_target_rejected",
            }:
                await self._breaker.record_failure()
            logger.warning(
                "direct_resolver_request_failed",
                source_domain=target.host,
                challenge_category=challenge_category,
                circuit_state=self._breaker.state,
                duration_ms=round((time.monotonic() - started_at) * 1000, 2),
                outcome=exc.code,
                retryable=exc.retryable,
            )
            raise

        logger.info(
            "direct_resolver_request_completed",
            source_domain=target.host,
            challenge_category=challenge_category,
            circuit_state=self._breaker.state,
            duration_ms=round((time.monotonic() - started_at) * 1000, 2),
            outcome="success",
            status_code=result.status_code,
        )
        return result

    async def _perform(
        self,
        target: ValidatedResolverTarget,
        declared_domains: tuple[str, ...],
    ) -> DirectResolverResult:
        endpoint = await self._validate_endpoint()
        request_url, host_header = _pinned_request_target(endpoint, "/v1")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Host": host_header,
            **self._authentication_headers,
        }
        extensions = {"sni_hostname": endpoint.host} if not endpoint.insecure_transport else None
        payload = {
            "cmd": "request.get",
            "url": target.url,
            "maxTimeout": round(self._timeout_seconds * 1000),
        }
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._http_client.stream(
                    "POST",
                    request_url,
                    headers=headers,
                    json=payload,
                    extensions=extensions,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise DirectResolverError(
                            "resolver_redirect_rejected",
                            "Resolver endpoint redirects are not permitted.",
                        )
                    content = await _read_bounded_response(response)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise DirectResolverError(
                "resolver_timed_out", "Resolver request timed out.", retryable=True
            ) from exc
        except httpx.TimeoutException as exc:
            raise DirectResolverError(
                "resolver_timed_out", "Resolver request timed out.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise DirectResolverError(
                "resolver_unavailable", "Resolver request failed.", retryable=True
            ) from exc

        if response.status_code in {401, 403}:
            raise DirectResolverError(
                "resolver_authentication_failed", "Resolver rejected its authentication."
            )
        if response.status_code == 429:
            raise DirectResolverError(
                "resolver_rate_limited", "Resolver is rate limited.", retryable=True
            )
        if response.status_code >= 400:
            raise DirectResolverError(
                "resolver_unavailable",
                f"Resolver returned HTTP {response.status_code}.",
                retryable=response.status_code >= 500,
            )
        try:
            decoded = _ResolverResponse.model_validate(json.loads(content))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise DirectResolverError(
                "resolver_malformed_response", "Resolver returned an invalid response."
            ) from exc

        try:
            returned_target = await validate_resolver_target(
                decoded.solution.url,
                declared_domains=declared_domains,
                resolver=self._target_resolver,
            )
        except DirectResolverError as exc:
            raise DirectResolverError(
                "resolver_redirect_rejected",
                "Resolver returned a URL outside the declared source domains.",
            ) from exc
        return DirectResolverResult(
            final_url=returned_target.url,
            status_code=decoded.solution.status,
            html=decoded.solution.response,
            cookies=tuple(
                DirectResolverCookie(
                    name=cookie.name,
                    value=cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                )
                for cookie in decoded.solution.cookies
            ),
            user_agent=decoded.solution.user_agent,
        )

    async def _validate_endpoint(self) -> ValidatedProviderEndpoint:
        try:
            return await validate_provider_endpoint(
                self._endpoint,
                allow_private_http=self._allow_private_http,
                resolver=self._endpoint_resolver,
            )
        except ProviderEndpointError as exc:
            raise DirectResolverError("resolver_endpoint_rejected", str(exc)) from exc


async def validate_resolver_target(
    raw_url: str,
    *,
    declared_domains: Sequence[str],
    resolver: ProviderEndpointResolver | None = None,
) -> ValidatedResolverTarget:
    """Reject source targets outside a provider or adapter-owned public allowlist."""
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 4_000:
        raise DirectResolverError("resolver_target_rejected", "Resolver target is invalid.")
    if not declared_domains or len(declared_domains) > _MAX_DECLARED_DOMAINS:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target domains are missing or unbounded."
        )
    try:
        parsed = urlsplit(raw_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target is malformed."
        ) from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target must use HTTP or HTTPS."
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target contains unsafe URL components."
        )
    host = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver targets must use a declared public domain."
        )

    normalized_domains = tuple(_normalize_domain(item) for item in declared_domains)
    if not any(host == domain or host.endswith(f".{domain}") for domain in normalized_domains):
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target is outside the declared domains."
        )

    effective_port = port or (443 if parsed.scheme == "https" else 80)
    resolve = resolver or _resolve_addresses
    try:
        addresses = await resolve(host, effective_port)
    except (OSError, TimeoutError) as exc:
        raise DirectResolverError(
            "resolver_target_rejected", "Resolver target could not be resolved."
        ) from exc
    if not addresses:
        raise DirectResolverError("resolver_target_rejected", "Resolver target did not resolve.")
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise DirectResolverError(
                "resolver_target_rejected", "Resolver target resolved unsafely."
            ) from exc
        if not address.is_global:
            raise DirectResolverError(
                "resolver_target_rejected", "Resolver target resolves to an unsafe network."
            )

    normalized_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = (
        normalized_host if effective_port == default_port else f"{normalized_host}:{effective_port}"
    )
    return ValidatedResolverTarget(
        url=urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, "")),
        host=host,
    )


def _normalize_domain(raw_domain: str) -> str:
    if not isinstance(raw_domain, str):
        raise DirectResolverError("resolver_target_rejected", "Declared domain is invalid.")
    domain = raw_domain.strip().lower().lstrip(".").rstrip(".")
    if (
        not domain
        or len(domain) > 253
        or "/" in domain
        or ":" in domain
        or "@" in domain
        or any(not label or len(label) > 63 for label in domain.split("."))
    ):
        raise DirectResolverError("resolver_target_rejected", "Declared domain is invalid.")
    return domain


def _validated_auth_headers(headers: dict[str, str]) -> dict[str, str]:
    if len(headers) > 4:
        raise ValueError("At most four resolver authentication headers are supported.")
    result: dict[str, str] = {}
    for name, value in headers.items():
        folded = name.casefold()
        if folded in _FORBIDDEN_HEADERS or folded.startswith("proxy-"):
            raise ValueError(f"Resolver header '{name}' is not permitted.")
        if not name or any(character.isspace() for character in name):
            raise ValueError("Resolver authentication header name is invalid.")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError("Resolver authentication header value is invalid.")
        result[name] = value
    return result


async def _read_bounded_response(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > _MAX_RESPONSE_BYTES:
            raise DirectResolverError(
                "resolver_response_too_large",
                "Resolver response exceeded the 8 MiB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _pinned_request_target(
    endpoint: ValidatedProviderEndpoint,
    path: str,
) -> tuple[str, str]:
    scheme = urlsplit(endpoint.url).scheme
    default_port = 443 if scheme == "https" else 80
    address = endpoint.addresses[0]
    address_host = f"[{address}]" if ":" in address else address
    original_host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
    if endpoint.port != default_port:
        address_host = f"{address_host}:{endpoint.port}"
        original_host = f"{original_host}:{endpoint.port}"
    return urlunsplit((scheme, address_host, path, "", "")), original_host


async def _resolve_addresses(host: str, port: int) -> Sequence[str]:
    from pullbox.providers.direct.endpoint import _resolve_addresses as resolve

    return await resolve(host, port)
