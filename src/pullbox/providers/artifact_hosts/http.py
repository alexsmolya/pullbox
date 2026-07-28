"""Bounded public-network HTTP primitives shared by artifact-host adapters."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.providers.artifact_hosts.contract import ArtifactHostResolutionError

ArtifactUrlResolver = Callable[[str, int], Awaitable[Sequence[str]]]

_MAX_URL_LENGTH = 4_000
_MAX_REDIRECTS = 3
_MAX_ADAPTER_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedArtifactUrl:
    """A normalized public HTTPS target resolved immediately before use."""

    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundedArtifactResponse:
    """A bounded response detached from the underlying network stream."""

    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str

    @property
    def text(self) -> str:
        encoding = _encoding_from_content_type(self.headers.get("content-type"))
        return self.content.decode(encoding, errors="replace")

    def json(self) -> object:
        return httpx.Response(200, content=self.content).json()


async def validate_artifact_url(
    raw_url: str,
    *,
    allowed_domains: Sequence[str] | None = None,
    resolver: ArtifactUrlResolver | None = None,
) -> ValidatedArtifactUrl:
    """Reject unsafe targets and DNS rebinding candidates before network I/O."""
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > _MAX_URL_LENGTH:
        raise _unsafe_url()
    try:
        parsed = urlsplit(raw_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise _unsafe_url() from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _unsafe_url()

    host = parsed.hostname.lower().rstrip(".")
    if allowed_domains and not any(_is_domain_or_subdomain(host, item) for item in allowed_domains):
        raise _unsafe_url()
    effective_port = port or 443
    resolve = resolver or _resolve_addresses
    try:
        raw_addresses = await resolve(host, effective_port)
    except (OSError, TimeoutError) as exc:
        raise ArtifactHostResolutionError(
            code="artifact_host_unavailable",
            message="The artifact host could not be resolved.",
            failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
            retryable=True,
            intervention=False,
        ) from exc
    if not raw_addresses:
        raise _unsafe_url()

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_address in raw_addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise _unsafe_url() from exc
        if not address.is_global:
            raise _unsafe_url()
        addresses.append(address)

    url_host = f"[{host}]" if ":" in host else host
    netloc = url_host if effective_port == 443 else f"{url_host}:{effective_port}"
    normalized = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    return ValidatedArtifactUrl(
        url=normalized,
        host=host,
        port=effective_port,
        addresses=tuple(str(address) for address in addresses),
    )


async def request_bounded(
    client: httpx.AsyncClient,
    method: str,
    raw_url: str,
    *,
    resolver: ArtifactUrlResolver | None,
    allowed_domains: Sequence[str] | None,
    headers: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
    max_response_bytes: int = _MAX_ADAPTER_RESPONSE_BYTES,
    max_redirects: int = _MAX_REDIRECTS,
) -> BoundedArtifactResponse:
    """Perform one bounded request while revalidating every redirect target."""
    current_url = raw_url
    current_method = method.upper()
    current_data = data
    for redirect_count in range(max_redirects + 1):
        target = await validate_artifact_url(
            current_url,
            allowed_domains=allowed_domains,
            resolver=resolver,
        )
        request_url, host_header = _pinned_request_target(target)
        request_headers = {**dict(headers or {}), "Host": host_header}
        request = client.build_request(
            current_method,
            request_url,
            headers=request_headers,
            data=current_data,
            extensions={"sni_hostname": target.host},
        )
        response: httpx.Response | None = None
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
            content = await _read_bounded(response, max_response_bytes)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise ArtifactHostResolutionError(
                code="artifact_host_unavailable",
                message="The artifact host is temporarily unavailable.",
                failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
                retryable=True,
                intervention=False,
            ) from exc
        finally:
            if response is not None:
                await response.aclose()

        if response.status_code not in {301, 302, 303, 307, 308}:
            return BoundedArtifactResponse(
                status_code=response.status_code,
                headers=response.headers,
                content=content,
                url=target.url,
            )
        if redirect_count == max_redirects:
            raise ArtifactHostResolutionError(
                code="artifact_host_redirect_limit",
                message="The artifact host returned too many redirects.",
                failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
                retryable=True,
                intervention=False,
            )
        location = response.headers.get("location")
        if not location:
            raise _contract_changed()
        current_url = urljoin(target.url, location)
        if response.status_code == 303 or (
            response.status_code in {301, 302} and current_method == "POST"
        ):
            current_method = "GET"
            current_data = None

    raise AssertionError("redirect loop must return or raise")


async def _read_bounded(response: httpx.Response, maximum: int) -> bytes:
    content = bytearray()
    async for chunk in response.aiter_bytes():
        content.extend(chunk)
        if len(content) > maximum:
            raise ArtifactHostResolutionError(
                code="artifact_host_response_too_large",
                message="The artifact host metadata response exceeded its safety limit.",
                failure_class=DirectArtifactFailureClass.SAFETY,
                retryable=False,
                intervention=True,
            )
    return bytes(content)


def _pinned_request_target(target: ValidatedArtifactUrl) -> tuple[str, str]:
    parsed = urlsplit(target.url)
    address = target.addresses[0]
    request_host = f"[{address}]" if ":" in address else address
    request_netloc = request_host if target.port == 443 else f"{request_host}:{target.port}"
    request_url = urlunsplit(("https", request_netloc, parsed.path, parsed.query, ""))
    host_header = target.host if target.port == 443 else f"{target.host}:{target.port}"
    return request_url, host_header


async def _resolve_addresses(host: str, port: int) -> Sequence[str]:
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    return tuple(sorted({str(record[4][0]) for record in records}))


def _encoding_from_content_type(content_type: str | None) -> str:
    if content_type:
        for part in content_type.split(";")[1:]:
            name, separator, value = part.partition("=")
            if separator and name.strip().lower() == "charset":
                return value.strip().strip('"') or "utf-8"
    return "utf-8"


def _is_domain_or_subdomain(hostname: str, domain: str) -> bool:
    normalized = domain.lower().rstrip(".")
    return hostname == normalized or hostname.endswith(f".{normalized}")


def _unsafe_url() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="unsafe_artifact_url",
        message="The artifact URL did not pass public HTTPS safety checks.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def _contract_changed() -> ArtifactHostResolutionError:
    return ArtifactHostResolutionError(
        code="artifact_host_contract_changed",
        message="The artifact host response no longer matches its supported contract.",
        failure_class=DirectArtifactFailureClass.PERMANENT_MIRROR,
        retryable=False,
        intervention=True,
    )
