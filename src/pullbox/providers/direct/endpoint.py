"""Network policy for manually registered direct-provider endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ProviderEndpointResolver = Callable[[str, int], Awaitable[Sequence[str]]]


class ProviderEndpointError(ValueError):
    """A safe endpoint-policy failure suitable for operator feedback."""


@dataclass(frozen=True, slots=True)
class ValidatedProviderEndpoint:
    """Normalized endpoint plus its current network classification."""

    url: str
    host: str
    port: int
    addresses: tuple[str, ...]
    private_network: bool
    insecure_transport: bool


async def validate_provider_endpoint(
    raw_url: str,
    *,
    allow_private_http: bool,
    resolver: ProviderEndpointResolver | None = None,
) -> ValidatedProviderEndpoint:
    """Resolve and validate a provider endpoint immediately before use."""
    if not isinstance(raw_url, str) or not raw_url.strip() or len(raw_url) > 1_000:
        raise ProviderEndpointError("Provider endpoint must be a bounded URL.")
    try:
        parsed = urlsplit(raw_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise ProviderEndpointError("Provider endpoint is malformed.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ProviderEndpointError("Provider endpoint must use HTTP or HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ProviderEndpointError("Provider endpoint cannot contain credentials.")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ProviderEndpointError(
            "Provider endpoint must not contain a path, query, or fragment."
        )

    effective_port = port or (443 if parsed.scheme == "https" else 80)
    resolve = resolver or _resolve_addresses
    try:
        raw_addresses = await resolve(parsed.hostname, effective_port)
    except (OSError, TimeoutError) as exc:
        raise ProviderEndpointError("Provider endpoint could not be resolved.") from exc
    if not raw_addresses:
        raise ProviderEndpointError("Provider endpoint did not resolve to an address.")

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_address in raw_addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ProviderEndpointError(
                "Provider endpoint resolved to an invalid address."
            ) from exc
        if (
            address.is_unspecified
            or address.is_multicast
            or address.is_link_local
            or address.is_reserved
        ):
            raise ProviderEndpointError("Provider endpoint resolves to an unsafe network address.")
        addresses.append(address)

    private_network = any(address.is_private or address.is_loopback for address in addresses)
    all_private = all(address.is_private or address.is_loopback for address in addresses)
    if private_network and not all_private:
        raise ProviderEndpointError("Provider endpoint returned mixed network address classes.")
    if parsed.scheme == "http":
        if not all_private:
            raise ProviderEndpointError("Public provider endpoints must use HTTPS.")
        if not allow_private_http:
            raise ProviderEndpointError("Registration must acknowledge private HTTP transport.")

    normalized_host = parsed.hostname.lower().rstrip(".")
    url_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = url_host if effective_port == default_port else f"{url_host}:{effective_port}"
    normalized_url = urlunsplit((parsed.scheme, netloc, "", "", ""))
    return ValidatedProviderEndpoint(
        url=normalized_url,
        host=normalized_host,
        port=effective_port,
        addresses=tuple(str(address) for address in addresses),
        private_network=private_network,
        insecure_transport=parsed.scheme == "http",
    )


async def _resolve_addresses(host: str, port: int) -> Sequence[str]:
    records = await asyncio.to_thread(
        socket.getaddrinfo,
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    return tuple(sorted({str(record[4][0]) for record in records}))
